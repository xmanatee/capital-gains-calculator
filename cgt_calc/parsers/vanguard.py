"""Vanguard transaction parser."""

from __future__ import annotations

import csv
import datetime
from decimal import Decimal
from pathlib import Path
import re
from typing import Final

from cgt_calc.exceptions import ParsingError, UnexpectedColumnCountError
from cgt_calc.model import ActionType, BrokerSource, BrokerTransaction

COLUMNS: Final[list[str]] = [
    "Date",
    "Details",
    "Amount",
    "Balance",
]

BOUGHT_RE: Final = re.compile(r"^Bought (\d*[,]?\d*(?:\.\d+)?) .*\((.*)\)$")
SOLD_RE: Final = re.compile(r"^Sold (\d*[,]?\d*(?:\.\d+)?) .*\((.*)\)$")
TRANSFER_RE: Final = re.compile(
    r".*(Regular Deposit|Deposit via|Deposit for|Payment by|Account Fee).*"
)


def _action_from_details(details: str, filename: str) -> ActionType:
    if TRANSFER_RE.match(details):
        return ActionType.TRANSFER
    if BOUGHT_RE.match(details):
        return ActionType.BUY
    if SOLD_RE.match(details):
        return ActionType.SELL
    raise ParsingError(filename, f"Unknown action: {details}")


class VanguardTransaction(BrokerTransaction):
    """Represents a single Vanguard transaction."""

    def __init__(self, header: list[str], row_raw: list[str], file: str):
        """Create transaction from CSV row."""
        if len(row_raw) != len(COLUMNS):
            raise UnexpectedColumnCountError(row_raw, len(COLUMNS), file)

        row = dict(zip(header, row_raw))

        date_str = row["Date"]
        date = datetime.datetime.strptime(date_str, "%d/%m/%Y").date()

        details = row["Details"]
        action = _action_from_details(details, file)

        fees = Decimal(0)
        currency = "GBP"
        amount = Decimal(row["Amount"].replace(",", ""))

        quantity: Decimal | None = None
        price: Decimal | None = None
        symbol: str | None = None

        if action is ActionType.BUY:
            match = BOUGHT_RE.match(details)
            if not match:
                raise ParsingError(file, f"Could not parse BUY details: {details}")
            quantity = Decimal(match.group(1).replace(",", ""))
            symbol = match.group(2)
            price = abs(amount) / quantity
        elif action is ActionType.SELL:
            match = SOLD_RE.match(details)
            if not match:
                raise ParsingError(file, f"Could not parse SELL details: {details}")
            quantity = Decimal(match.group(1).replace(",", ""))
            symbol = match.group(2)
            price = amount / quantity

        super().__init__(
            date=date,
            action=action,
            symbol=symbol,
            description=details,
            quantity=quantity,
            price=price,
            fees=fees,
            amount=amount,
            currency=currency,
            broker_source=BrokerSource.VANGUARD,
        )


def _validate_header(header: list[str], filename: str) -> None:
    """Check if header is valid."""
    for actual in header:
        if actual not in COLUMNS:
            raise ParsingError(filename, f"Unknown column {actual}")


def read_vanguard_transactions(transactions_file: str) -> list[VanguardTransaction]:
    """Read Vanguard transactions from file."""
    file_path = Path(transactions_file)
    try:
        with file_path.open(encoding="utf-8") as csv_file:
            lines = list(csv.reader(csv_file))
    except FileNotFoundError:
        print(
            f"WARNING: Couldn't locate Vanguard transactions file({transactions_file})"
        )
        return []

    if not lines:
        print(f"WARNING: No transactions detected in file {transactions_file}")
        return []

    header = lines[0]
    _validate_header(header, transactions_file)
    transactions = [
        VanguardTransaction(header, row, transactions_file)
        for row in lines[1:]
        if any(cell.strip() for cell in row)
    ]
    transactions.sort(key=lambda t: (t.date, t.action == ActionType.BUY))
    return transactions
