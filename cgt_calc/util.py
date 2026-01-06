"""Utility functions."""

from __future__ import annotations

import decimal
from decimal import Decimal
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TextIO


def round_decimal(value: Decimal, digits: int = 0) -> Decimal:
    """Round decimal to given precision."""
    with decimal.localcontext() as ctx:
        ctx.rounding = decimal.ROUND_HALF_UP
        return Decimal(round(value, digits))


def strip_zeros(value: Decimal) -> str:
    """Strip trailing zeros from Decimal."""
    return f"{value:.10f}".rstrip("0").rstrip(".")


def luhn_check_digit(payload: str) -> int:
    """Return the check digit given a string of numbers using the Luhn Algorithm.

    Reference: https://en.wikipedia.org/wiki/Luhn_algorithm
    """
    if len(payload) % 2 == 1:
        payload = f"0{payload}"
    checksum = 0
    for idx, digit_char in enumerate(payload[::-1]):
        digit = int(digit_char)
        if idx % 2 == 0:
            digit *= 2
            if digit > 9:  # noqa: PLR2004
                digit -= 9
        checksum += digit
    return (10 - (checksum % 10)) % 10


def is_isin(isin: str) -> bool:
    """Validate if a string is a valid ISIN."""
    isin_regex = r"^([A-Z]{2})([A-Z0-9]{9})([0-9])$"
    char_to_digit = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    if not re.match(isin_regex, isin):
        return False
    payload = isin[:11]
    check_digit = int(isin[11])
    numeric_payload = "".join(str(char_to_digit.index(c)) for c in payload)
    return luhn_check_digit(numeric_payload) == check_digit


def open_with_parents(path: Path) -> TextIO:
    """Open a file for writing, creating parent directories if they do not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf8")
