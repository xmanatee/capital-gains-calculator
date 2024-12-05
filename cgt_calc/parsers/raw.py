"""Raw transaction parser."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from cgt_calc.model import ActionType, BrokerSource, BrokerTransaction
from cgt_calc.parsers.base import Column, CsvParser
import cgt_calc.parsers.field_parsers as parse

if TYPE_CHECKING:
    from cgt_calc.parsers.field_parsers import ParsedFieldType

RAW_CSV_COLUMNS: Final[list[Column]] = [
    Column("date", parse.date_format("%Y-%m-%d")),
    Column("action", lambda s: ActionType[s.upper()]),
    Column("symbol", parse.optional(parse.symbol)),
    Column("quantity", parse.optional(parse.decimal)),
    Column("price", parse.optional(parse.decimal)),
    Column("fees", parse.decimal),
    Column("currency", str),
]


class RawParser(CsvParser):
    """Parser for Raw transactions."""

    def required_columns(self) -> list[Column]:
        return RAW_CSV_COLUMNS

    def parse_row(
        self, row: dict[str, ParsedFieldType], raw_row: dict[str, str]
    ) -> BrokerTransaction:
        action = row["action"]
        quantity = row["quantity"]
        price = row["price"]
        fees = row["fees"]
        amount = None

        if price is not None and quantity is not None:
            amount = price * quantity
            if action == ActionType.BUY:
                amount = -abs(amount)
            amount -= fees

        return BrokerTransaction(
            date=row["date"],
            action=action,
            symbol=row["symbol"],
            description="",
            quantity=quantity,
            price=price,
            fees=fees,
            amount=amount,
            currency=row["currency"],
            broker_source=BrokerSource.UNKNOWN,
        )


def read_raw_transactions(transactions_file: str) -> list[BrokerTransaction]:
    """Read Raw transactions from file."""
    file_path = Path(transactions_file)
    return RawParser().parse_file(file_path)
