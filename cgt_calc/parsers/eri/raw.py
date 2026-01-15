"""Raw transaction parser."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import datetime
from decimal import Decimal, InvalidOperation
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

from cgt_calc.exceptions import ParsingError
from cgt_calc.util import is_isin

from .model import EriTransaction

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

    from cgt_calc.isin_converter import IsinConverter

COLUMNS: Final[list[str]] = [
    "ISIN",
    "Fund Reporting Period End Date",
    "Currency",
    "Excess of reporting income over distribution",
]
LOGGER = logging.getLogger(__name__)


@dataclass
class EriRawData:
    """Parsed ERI row data before symbol resolution."""

    isin: str
    date: datetime.date
    price: Decimal
    currency: str


def parse_eri_row(header: list[str], row_raw: list[str], file: Path) -> EriRawData:
    """Parse a single CSV row into ERI data."""
    if len(row_raw) != len(COLUMNS):
        raise ParsingError(
            str(file), f"expected {len(COLUMNS)} columns, got {len(row_raw)}"
        )

    row = dict(zip(header, row_raw, strict=True))

    isin = row["ISIN"]
    if not is_isin(isin):
        raise ParsingError(file, f"Invalid ISIN value '{isin}' in ERI data")

    date_str = row["Fund Reporting Period End Date"]
    try:
        date = datetime.datetime.strptime(date_str, "%d/%m/%Y").date()
    except ValueError as err:
        raise ParsingError(file, f"Invalid date '{date_str}' in ERI data") from err

    currency = row["Currency"]
    price_str = row["Excess of reporting income over distribution"]
    try:
        price = Decimal(price_str)
    except (InvalidOperation, ValueError) as err:
        raise ParsingError(file, f"Invalid decimal '{price_str}' in ERI data") from err

    return EriRawData(isin=isin, date=date, price=price, currency=currency)


def validate_header(header: list[str], file: Path, columns: list[str]) -> None:
    """Check if header is valid."""
    missing = set(columns) - set(header)
    if missing:
        cols = ", ".join(sorted(missing))
        raise ParsingError(file, f"Missing required columns: {cols}")
    for actual in header:
        if actual not in columns:
            raise ParsingError(file, f"Unknown column: {actual}")


def read_eri_raw(
    eri_file: Path | Traversable,
    isin_converter: IsinConverter,
) -> list[EriTransaction]:
    """Read ERI raw transactions from file."""
    file_label = (
        eri_file if isinstance(eri_file, Path) else Path("resources") / eri_file.name
    )

    with eri_file.open(encoding="utf-8") as csv_file:
        lines = list(csv.reader(csv_file))

    if not lines:
        raise ParsingError(file_label, "ERI data file is empty")

    header = lines[0]
    validate_header(header, file_label, COLUMNS)

    raw_data = [parse_eri_row(header, row, file_label) for row in lines[1:]]
    if not raw_data:
        LOGGER.warning("No transactions detected in file: %s", eri_file)
        return []

    transactions: list[EriTransaction] = []
    for data in raw_data:
        symbol = isin_converter.get(data.isin)
        transactions.append(
            EriTransaction(
                date=data.date,
                symbol=symbol,
                isin=data.isin,
                price=data.price,
                currency=data.currency,
            )
        )

    return transactions
