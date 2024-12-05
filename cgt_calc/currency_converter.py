from __future__ import annotations

from collections import defaultdict
import csv
import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from cgt_calc.exceptions import ExchangeRateMissingError

if TYPE_CHECKING:
    from cgt_calc.model import BrokerTransaction


class CurrencyConverter:
    def __init__(
        self,
        currencies: list[str],
        data_dir: str = "exchange_rates",
    ):
        self.currencies = [currency.upper() for currency in currencies]
        self.data_dir = Path(data_dir)
        self.exchange_rates: dict[str, dict[datetime.date, Decimal]] = defaultdict(dict)
        # Load data from files
        self._load_exchange_rates()

    def _load_exchange_rates(self) -> None:
        """Load exchange rates from files per currency."""
        for currency in self.currencies:
            currency_file = self.data_dir / f"{currency}.csv"
            with currency_file.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader)  # Skip header
                for row in reader:
                    month_str, rate_str = row
                    month_date = datetime.datetime.strptime(month_str, "%Y-%m").date()
                    rate = Decimal(rate_str)
                    self.exchange_rates[currency][month_date] = rate

    def get_rate(self, currency: str, date: datetime.date) -> Decimal:
        """Get the exchange rate for a given currency and date (month)."""
        currency = currency.upper()
        month_date = date.replace(day=1)
        if currency == "GBP":
            return Decimal("1.0")
        if currency not in self.exchange_rates:
            raise ValueError(f"Currency {currency} not in converter currencies.")
        if month_date in self.exchange_rates[currency]:
            return self.exchange_rates[currency][month_date]
        raise ExchangeRateMissingError(currency, date)

    def to_gbp(self, amount: Decimal, currency: str, date: datetime.date) -> Decimal:
        """Convert amount from given currency to GBP."""
        if currency == "GBP":
            return amount
        rate = self.get_rate(currency, date)
        return amount / rate

    def to_gbp_for(self, amount: Decimal, transaction: BrokerTransaction) -> Decimal:
        """Convert amount from transaction currency to GBP."""

        return self.to_gbp(amount, transaction.currency, transaction.date)
