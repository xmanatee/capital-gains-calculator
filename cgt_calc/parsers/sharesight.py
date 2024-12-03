"""Sharesight parser."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from cgt_calc.const import TICKER_RENAMES
from cgt_calc.exceptions import InvalidTransactionError, ParsingError
from cgt_calc.model import ActionType, BrokerTransaction
from cgt_calc.parsers.base import Column, CsvParser
import cgt_calc.parsers.field_parsers as parse

if TYPE_CHECKING:
    from collections.abc import Iterator

    from cgt_calc.parsers.base import ParsedRowType
    from cgt_calc.parsers.field_parsers import ParsedFieldType

STOCK_ACTIVITY_COMMENT_MARKER = "Stock Activity"

SHARESIGHT_TRADE_COLUMNS = [
    Column("Market", str),
    Column("Code", parse.symbol),
    Column("Date", parse.date_format("%d/%m/%Y")),
    Column("Type", parse.one_of(["Buy", "Sell"])),
    Column("Quantity", parse.decimal),
    Column("Price *", parse.decimal),
    Column("Brokerage *", parse.optional(parse.decimal, Decimal(0))),
    Column("Value", parse.optional(parse.decimal)),
    Column("Currency", str),
    Column("Comments", str),
]


class SharesightTradesParser(CsvParser):
    """Parser for Sharesight All Trades Report."""

    def required_columns(self) -> list[Column]:
        return SHARESIGHT_TRADE_COLUMNS

    def parse_row(
        self, row: dict[str, ParsedFieldType], raw_row: dict[str, str]
    ) -> BrokerTransaction:
        action = ActionType.BUY if row["Type"] == "Buy" else ActionType.SELL

        market = row["Market"]
        symbol = f"{market}:{row['Code']}"
        quantity = row["Quantity"]
        price = row["Price *"]
        fees = row["Brokerage *"] or Decimal(0)
        currency = row["Currency"]
        description = row["Comments"]
        gbp_value = row["Value"]

        # Sharesight's reports conventions are slightly different from our
        # conventions:
        # - Quantity is negative on sell
        # - Amount is negative when selling, and positive when buying
        #   (as it tracks portfolio value, not account balance)
        # - Value provided is always in GBP
        # - Foreign exchange transactions are show as BUY and SELL

        if market == "FX":
            # While Sharesight provides an exchange rate, it is not precise enough
            # for cryptocurrency transactions
            if not gbp_value:
                raise ValueError("Missing Value in FX transaction")
            price = abs(gbp_value / quantity)
            currency = "GBP"

        amount = -(quantity * price) - fees
        quantity = abs(quantity)

        transaction = BrokerTransaction(
            date=row["Date"],
            action=action,
            symbol=symbol,
            description=description,
            quantity=quantity,
            price=price,
            fees=fees,
            amount=amount,
            currency=currency,
            broker="Sharesight",
        )

        # Sharesight has no native support for stock activity, so use a string
        # in the trade comment to mark it
        if STOCK_ACTIVITY_COMMENT_MARKER.lower() in description.lower():
            # Stock activity that is not a grant is weird and unsupported
            if action != ActionType.BUY:
                raise InvalidTransactionError(
                    transaction, "Stock activity must have Type=Buy"
                )
            transaction.action = ActionType.STOCK_ACTIVITY
            transaction.amount = None

        return transaction

    def parse_file(self, file: Path) -> list[BrokerTransaction]:
        transactions = []
        with file.open(encoding="utf-8") as csv_file:
            reader = csv.reader(csv_file)
            # Skip to the header row
            for row_line in reader:
                if row_line and row_line[0] == "Market":
                    headers = row_line
                    break
            else:
                raise ParsingError(str(file), "Could not find header row")

            for row_values in reader:
                if not any(row_values):
                    break  # End of trades section
                row = dict(zip(headers, row_values))
                parsed_row = {}
                for col in self.required_columns():
                    parsed_row.update(col.parse(row))
                transaction = self.parse_row(parsed_row, row)
                transactions.append(transaction)
        return transactions


class SharesightIncomeParser(CsvParser):
    """Parser for Sharesight Taxable Income Report."""

    def required_columns(self) -> list[Column]:
        # Columns vary between sections; we'll handle them dynamically
        return []

    def parse_row(
        self, row: dict[str, ParsedFieldType], raw_row: dict[str, str]
    ) -> ParsedRowType:
        pass

    def parse_file(self, file: Path) -> list[BrokerTransaction]:
        transactions = []

        with file.open(encoding="utf-8") as csv_file:
            rows = list(csv.reader(csv_file))

        rows_iter = iter(rows)
        for row in rows_iter:
            if row[0] == "Local Income":
                transactions += self.parse_local_income(rows_iter)
            elif row[0] == "Foreign Income":
                transactions += self.parse_dividend_payments(rows_iter, is_foreign=True)
        return transactions

    def parse_local_income(
        self, rows_iter: Iterator[list[str]]
    ) -> list[BrokerTransaction]:
        transactions = []
        for row in rows_iter:
            if row[0] == "Total Local Income":
                break
            if row[0] == "Dividend Payments":
                transactions += self.parse_dividend_payments(
                    rows_iter, is_foreign=False
                )
        return transactions

    def parse_dividend_payments(
        self, rows_iter: Iterator[list[str]], is_foreign: bool
    ) -> list[BrokerTransaction]:
        transactions: list[BrokerTransaction] = []
        columns = next(rows_iter, None)
        if columns is None:
            return transactions

        for row in rows_iter:
            if row[0] == "Total":
                break
            row_dict = dict(zip(columns, row))

            dividend_date = parse.date_format("%d/%m/%Y")(row_dict["Date Paid"])
            symbol = row_dict["Code"]
            symbol = TICKER_RENAMES.get(symbol, symbol)
            description = row_dict["Comments"]

            if is_foreign:
                currency = row_dict["Currency"]
                amount = parse.decimal(row_dict["Gross Amount"])
                tax = parse.optional(parse.decimal)(row_dict["Foreign Tax Deducted"])
            else:
                amount = parse.decimal(row_dict["Gross Dividend"])
                tax = parse.optional(parse.decimal)(row_dict["Tax Deducted"])
                currency = "GBP"

            transactions.append(
                BrokerTransaction(
                    date=dividend_date,
                    action=ActionType.DIVIDEND,
                    symbol=symbol,
                    description=description,
                    broker="Sharesight",
                    currency=currency,
                    amount=amount,
                    quantity=None,
                    price=None,
                    fees=Decimal(0),
                )
            )

            if tax:
                transactions.append(
                    BrokerTransaction(
                        date=dividend_date,
                        action=ActionType.TAX,
                        symbol=symbol,
                        description=description,
                        broker="Sharesight",
                        currency=currency,
                        amount=-tax,
                        quantity=None,
                        price=None,
                        fees=Decimal(0),
                    )
                )
        return transactions


def read_sharesight_transactions(
    transactions_folder: str,
) -> list[BrokerTransaction]:
    """Parse Sharesight transactions from reports."""

    transactions: list[BrokerTransaction] = []
    trades_parser = SharesightTradesParser()
    income_parser = SharesightIncomeParser()

    for file in Path(transactions_folder).glob("*.csv"):
        if file.match("Taxable Income Report*.csv"):
            transactions += income_parser.parse_file(file)
        if file.match("All Trades Report*.csv"):
            transactions += trades_parser.parse_file(file)

    transactions.sort(key=lambda t: t.date)
    return transactions
