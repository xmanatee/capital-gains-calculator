"""Initial stock prices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dates import is_date
from .exceptions import ExchangeRateMissingError
from .validation import check

if TYPE_CHECKING:
    import datetime
    from decimal import Decimal


@dataclass
class InitialPrices:
    """Class to store initial stock prices."""

    initial_prices: dict[datetime.date, dict[str, Decimal]]

    def get(self, date: datetime.date, symbol: str) -> Decimal:
        """Get initial stock price at given date."""
        check(is_date(date), f"invalid date: {date}")
        if date not in self.initial_prices or symbol not in self.initial_prices[date]:
            raise ExchangeRateMissingError(symbol, date)
        return self.initial_prices[date][symbol]
