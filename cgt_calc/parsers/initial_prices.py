from __future__ import annotations

from typing import TYPE_CHECKING, Final

from cgt_calc.parsers.base import Column, CsvParser
import cgt_calc.parsers.field_parsers as parse

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from cgt_calc.parsers.field_parsers import ParsedFieldType

INITIAL_PRICES_CSV_COLUMNS: Final[list[Column]] = [
    Column("date", parse.date_format("%b %d, %Y")),
    Column("symbol", parse.symbol),
    Column("price", parse.decimal),
]


class InitialPricesParser(CsvParser):
    def required_columns(self) -> list[Column]:
        return INITIAL_PRICES_CSV_COLUMNS

    def parse_row(
        self, row: dict[str, ParsedFieldType], raw_row: dict[str, str]
    ) -> tuple[date, str, Decimal]:
        return (row["date"], row["symbol"], row["price"])
