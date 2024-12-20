"""Trading 212 parser."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from cgt_calc.model import ActionType, BrokerSource, BrokerTransaction
from cgt_calc.parsers.base import Column, CsvParser
import cgt_calc.parsers.field_parsers as parse

if TYPE_CHECKING:
    from collections.abc import Callable

    from cgt_calc.parsers.field_parsers import ParsedFieldType


def parse_trading212_action(label: str) -> ActionType:
    if label in [
        "Market buy",
        "Limit buy",
        "Stop buy",
    ]:
        return ActionType.BUY

    if label in [
        "Market sell",
        "Limit sell",
        "Stop sell",
    ]:
        return ActionType.SELL

    if label in [
        "Deposit",
        "Withdrawal",
    ]:
        return ActionType.TRANSFER

    if label in [
        "Dividend (Ordinary)",
        "Dividend (Dividend)",
        "Dividend (Dividends paid by us corporations)",
    ]:
        return ActionType.DIVIDEND

    if label in ["Interest on cash"]:
        return ActionType.INTEREST

    if label == "Stock Split":
        return ActionType.STOCK_SPLIT

    raise ValueError(f"Unknown action: {label}")


def parse_trading212_time(val: str) -> datetime:
    return datetime.strptime(
        val, "%Y-%m-%d %H:%M:%S.%f" if "." in val else "%Y-%m-%d %H:%M:%S"
    )


class Trading212Column(Column):
    def __init__(
        self,
        csv_name: str,
        parser: Callable[[str], ParsedFieldType],
        is_optional: bool = False,
    ):
        super().__init__(csv_name, parser)
        self._ac = f"Currency ({self.csv_name})"
        self._dc = f"{self.csv_name} (GBP)"
        self.is_optional = is_optional

    def is_present(self, headers: list[str]) -> bool:
        if self.csv_name in headers and self._ac in headers:
            return True

        return self._dc in headers or self.is_optional

    def parse(self, row: dict[str, str]) -> dict[str, ParsedFieldType]:
        if self.csv_name in row and self._ac in row:
            assert self._dc not in row

            return {
                self.csv_name: self.parser(row[self.csv_name]),
                self._ac: row[self._ac],
            }

        if self._dc in row:
            return {
                self.csv_name: self.parser(row[self._dc]),
                self._ac: "GBP",
            }

        if self.is_optional:
            return {
                self.csv_name: Decimal(0),
                self._ac: "GBP",
            }

        raise ValueError(f"No column for {self.csv_name} found in {row}")


class Trading212Parser(CsvParser):
    """Parser for Trading 212 transactions."""

    def required_columns(self) -> list[Column]:
        return [
            Column("Action", parse_trading212_action),
            Column("Time", parse_trading212_time),
            Column("ISIN", parse.optional(str)),
            Column("Ticker", parse.optional(parse.symbol)),
            Column("Name", parse.optional(str)),
            Column("No. of shares", parse.optional(parse.decimal)),
            Column(
                "Exchange rate",
                parse.optional(parse.decimal, none_values=["Not available"]),
            ),
            Column("Notes", parse.optional(str)),
            Column("ID", parse.optional(str)),
            Trading212Column("Price / share", parse.optional(parse.decimal)),
            Trading212Column("Result", parse.optional(parse.decimal)),
            Trading212Column("Total", parse.decimal),
            Trading212Column(
                "Withholding tax",
                parse.optional(parse.decimal, Decimal(0)),
                is_optional=True,
            ),
            Trading212Column(
                "Transaction fee",
                parse.optional(parse.decimal, Decimal(0)),
                is_optional=True,
            ),
            Trading212Column(
                "Finra fee",
                parse.optional(parse.decimal, Decimal(0)),
                is_optional=True,
            ),
            Trading212Column(
                "Currency conversion fee",
                parse.optional(parse.decimal, Decimal(0)),
                is_optional=True,
            ),
            Trading212Column(
                "Stamp duty",
                parse.optional(parse.decimal, Decimal(0)),
                is_optional=True,
            ),
            # Trading212Column("Charge amount"),
        ]

    def parse_row(
        self, row: dict[str, ParsedFieldType], raw_row: dict[str, str]
    ) -> BrokerTransaction:
        # isin = row["ISIN"]
        # transaction_id = row.get("ID")

        date = row["Time"].date()
        action = row["Action"]
        symbol = row["Ticker"]
        description = f"{row["Name"]} : {row["Notes"]}"
        quantity = row["No. of shares"]

        amount = row["Total"]
        currency = row["Currency (Total)"]

        fees = self._calculate_fees(row)

        if (
            action == ActionType.BUY or raw_row["Action"] == "Withdrawal"
        ) and amount > 0:
            amount = -amount
        price = (
            abs(amount + fees) / quantity
            if amount is not None and quantity is not None
            else None
        )

        return BrokerTransaction(
            date=date,
            action=action,
            symbol=symbol,
            description=description,
            quantity=quantity,
            price=price,
            fees=fees,
            amount=amount,
            currency=currency,
            broker_source=BrokerSource.TRADING_212,
        )

    def _calculate_fees(self, row: dict[str, ParsedFieldType]) -> Decimal:
        fee_columns = [
            "Withholding tax",
            "Transaction fee",
            "Finra fee",
            "Stamp duty",
            "Currency conversion fee",
        ]
        fees = Decimal()
        for fee_column in fee_columns:
            if row[f"Currency ({fee_column})"] != "GBP":
                print(
                    f"WARNING: ignoring currency of '{fee_column}' when "
                    "calculating fees"
                )
            fees += row[fee_column]
        return fees

    def _maybe_check_price_discrepancy(
        self, price: Decimal | None, row: dict[str, ParsedFieldType]
    ) -> None:
        if price is None or row["Price / share"] is None:
            return

        if row["Currency (Price / share)"] == "GBP":
            calculated_price_foreign = price
        elif row["Exchange rate"] is not None:
            calculated_price_foreign = price * row["Exchange rate"]
        else:
            return

        discrepancy = row["Price / share"] - calculated_price_foreign
        if abs(discrepancy) > Decimal("0.015"):
            print(
                "WARNING: The Price / share for this transaction "
                "after converting and adding in the fees "
                f"doesn't add up to the total amount: {row}. "
                "You may fix the csv by looking at the transaction "
                f"in the UI. Discrepancy / share: {discrepancy:.3f}."
            )


def read_trading212_transactions(transactions_folder: str) -> list[BrokerTransaction]:
    """Parse Trading 212 transactions from CSV files."""
    transactions = []
    parser = Trading212Parser()
    for file in Path(transactions_folder).glob("*.csv"):
        transactions += parser.parse_file(file)
    transactions.sort(key=lambda t: (t.date, t.action == ActionType.BUY))
    return transactions
