from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Final

from cgt_calc.const import TICKER_RENAMES
from cgt_calc.model import ActionType, BrokerSource, BrokerTransaction
from cgt_calc.parsers.base import Column, CsvParser
import cgt_calc.parsers.field_parsers as parse

if TYPE_CHECKING:
    from cgt_calc.parsers.field_parsers import ParsedFieldType

KNOWN_SYMBOL_DICT: Final[dict[str, str]] = {
    "GSU Class C": "GOOG",
    "Cash": "USD",
}


@dataclass
class StockSplit:
    """Info about stock split."""

    symbol: str
    date: date
    factor: int


STOCK_SPLIT_INFO = [
    StockSplit(symbol="GOOG", date=datetime(2022, 6, 15).date(), factor=20),
]


class MorganStanleyReleaseParser(CsvParser):
    def required_columns(self) -> list[Column]:
        return [
            Column("Vest Date", parse.date_format("%d-%b-%Y")),
            Column("Order Number", str),
            Column("Plan", parse.const_map(KNOWN_SYMBOL_DICT)),
            Column("Type", parse.const_value("Release")),
            Column("Status", parse.one_of(["Complete", "Staged"])),
            Column("Price", parse.dollar_amount),
            Column("Quantity", parse.decimal),
            Column("Net Cash Proceeds", parse.const_value("$0.00")),
            Column("Net Share Proceeds", parse.decimal),
            Column("Tax Payment Method", str),
        ]

    def parse_row(
        self, row: dict[str, ParsedFieldType], raw_row: dict[str, str]
    ) -> BrokerTransaction:
        quantity = row["Net Share Proceeds"]
        price = row["Price"]
        amount = quantity * price
        symbol = row["Plan"]
        symbol = TICKER_RENAMES.get(symbol, symbol)

        return BrokerTransaction(
            date=row["Vest Date"],
            action=ActionType.STOCK_ACTIVITY,
            symbol=symbol,
            description=row["Plan"],
            quantity=quantity,
            price=price,
            fees=Decimal(0),
            amount=amount,
            currency="USD",
            broker_source=BrokerSource.MSSB_RELEASE,
        )


class MorganStanleyWithdrawalParser(CsvParser):
    def required_columns(self) -> list[Column]:
        return [
            Column("Execution Date", parse.date_format("%d-%b-%Y")),
            Column("Order Number", str),
            Column("Plan", parse.const_map(KNOWN_SYMBOL_DICT)),
            Column("Type", parse.const_value("Sale")),
            Column("Order Status", parse.const_value("Complete")),
            Column("Price", parse.dollar_amount),
            Column("Quantity", parse.decimal),
            Column("Net Amount", parse.dollar_amount),
            Column("Net Share Proceeds", parse.dollar_amount),
            Column("Tax Payment Method", str),
        ]

    def parse_row(
        self, row: dict[str, ParsedFieldType], raw_row: dict[str, str]
    ) -> BrokerTransaction:
        quantity = -row["Quantity"]
        price = row["Price"]
        amount = row["Net Amount"]
        fees = quantity * price - amount
        symbol = row["Plan"]

        if symbol == "USD":
            action = ActionType.TRANSFER
            amount *= -1
        else:
            action = ActionType.SELL

        transaction = BrokerTransaction(
            date=row["Execution Date"],
            action=action,
            symbol=symbol,
            description=row["Plan"],
            quantity=quantity,
            price=price,
            fees=fees,
            amount=amount,
            currency="USD",
            broker_source=BrokerSource.MSSB_WITHDRAWAL,
        )

        return self._handle_stock_split(transaction)

    def _handle_stock_split(self, transaction: BrokerTransaction) -> BrokerTransaction:
        for split in STOCK_SPLIT_INFO:
            if (
                transaction.symbol == split.symbol
                and transaction.action == ActionType.SELL
                and transaction.date < split.date
            ):
                if transaction.quantity:
                    transaction.quantity *= split.factor
                if transaction.price:
                    transaction.price /= split.factor
        return transaction

    def parse_file(self, file: Path) -> list[BrokerTransaction]:
        # Morgan Stanley decided to put a notice in the end of the withdrawal report
        # that looks like that:
        # "Please note that any Alphabet share sales, transfers, or deposits that
        # occurred on or prior to the July 15, 2022 stock split are reflected in
        # pre-split. Any sales, transfers, or deposits that occurred after July 15,
        # 2022 are in post-split values. For GSU vests, your activity is displayed in
        # post-split values."
        # It makes sense, but it totally breaks the CSV parsing
        with file.open(encoding="utf-8") as csv_file:
            lines = csv_file.readlines()
        lines = [line for line in lines if not line.startswith("Please note")]
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w", encoding="utf-8"
        ) as temp_file:
            temp_file.writelines(lines)
            temp_file_path = temp_file.name

        return super().parse_file(Path(temp_file_path))


def read_mssb_transactions(transactions_folder: str) -> list[BrokerTransaction]:
    """Parse Morgan Stanley transactions from CSV files."""
    transactions: list[BrokerTransaction] = []

    for file in Path(transactions_folder).glob("*.csv"):
        if Path(file).name == "Withdrawals Report.csv":
            transactions += MorganStanleyWithdrawalParser().parse_file(file)
        elif Path(file).name == "Releases Report.csv":
            transactions += MorganStanleyReleaseParser().parse_file(file)
    return transactions
