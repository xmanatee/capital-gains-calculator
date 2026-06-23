"""Exceptions for CGT calculator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cgt_calc.validation import ParsingError, TransactionError

if TYPE_CHECKING:
    import datetime

__all__ = [
    "CalculationError",
    "ExchangeRateMissingError",
    "ExternalApiError",
    "IsinTranslationError",
    "ParsingError",
    "TransactionError",
]


class CalculationError(Exception):
    """Calculation error base class."""


class ExchangeRateMissingError(CalculationError):
    """Exchange rate not found for currency/date."""

    def __init__(self, symbol: str, date: datetime.date):
        super().__init__(f"No exchange rate for {symbol} on {date}")


class ExternalApiError(Exception):
    """External API call failed."""


class IsinTranslationError(Exception):
    """ISIN to ticker translation failed."""
