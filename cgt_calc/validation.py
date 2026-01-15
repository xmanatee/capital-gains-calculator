"""Preconditions - minimal validation utilities.

Inspired by Java Guava Preconditions. Provides a small, consistent API
for validating preconditions throughout the codebase.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from cgt_calc.model import BrokerTransaction

T = TypeVar("T")


# === Exceptions ===


class ParsingError(Exception):
    """Parsing error with file context."""

    def __init__(self, file: str, message: str):
        super().__init__(f"Parsing {file}: {message}")


class TransactionError(Exception):
    """Transaction error with transaction context."""

    def __init__(self, tx: BrokerTransaction, message: str):
        super().__init__(f"{message}\nTransaction: {tx}")


# === Core Preconditions (raise ValueError) ===


def check(condition: bool, msg: str) -> None:
    """Check a precondition. Raises ValueError if false."""
    if not condition:
        raise ValueError(msg)


def check_not_none(value: T | None, msg: str = "value required") -> T:
    """Check value is not None. Returns value for type narrowing."""
    if value is None:
        raise ValueError(msg)
    return value


def check_non_negative(value: Decimal, msg: str = "must be >= 0") -> Decimal:
    """Check value >= 0. Returns value for chaining."""
    if value < 0:
        raise ValueError(f"{msg}: {value}")
    return value


# === Context-aware Preconditions ===


def check_tx(tx: BrokerTransaction, condition: bool, msg: str) -> None:
    """Check transaction condition. Raises TransactionError."""
    if not condition:
        raise TransactionError(tx, msg)


def check_tx_field(tx: BrokerTransaction, value: T | None, field: str) -> T:
    """Check transaction field is not None. Returns value."""
    if value is None:
        raise TransactionError(tx, f"{field} required")
    return value
