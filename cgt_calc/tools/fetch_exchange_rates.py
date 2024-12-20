from __future__ import annotations

from collections import defaultdict
import csv
import datetime
from decimal import Decimal
from pathlib import Path
import sys

from defusedxml import ElementTree as ET
import requests


class FetchExchangeRates:
    NEW_ENDPOINT_FROM_YEAR = 2021
    HMRC_OLD_URL_TEMPLATE = (
        "http://www.hmrc.gov.uk/softwaredevelopers/rates/"
        "exrates-monthly-{month_str}.xml"
    )
    HMRC_NEW_URL_TEMPLATE = (
        "https://www.trade-tariff.service.gov.uk/api/v2/"
        "exchange_rates/files/monthly_xml_{month_str}.xml"
    )

    def __init__(
        self,
        start_year: int,
        end_year: int,
        data_dir: str = "exchange_rates",
    ):
        self.data_dir = Path(data_dir)
        self.start_year = start_year
        self.end_year = end_year

        # Exchange rates: {currency: {month_date: rate}}
        self.exchange_rates: dict[str, dict[datetime.date, Decimal]] = defaultdict(dict)

    def _load_existing_exchange_rates(self) -> None:
        if not self.data_dir.exists():
            return

        for currency_file in self.data_dir.glob("*.csv"):
            currency = currency_file.stem.upper()
            with currency_file.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader)  # Skip header
                for row in reader:
                    month_str, rate_str = row
                    month_date = datetime.datetime.strptime(month_str, "%Y-%m").date()
                    rate = Decimal(rate_str)
                    self.exchange_rates[currency][month_date] = rate

    def _save_exchange_rates(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for currency, rates in self.exchange_rates.items():
            currency_file = self.data_dir / f"{currency}.csv"
            with currency_file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["month", "rate"])
                for month_date, rate in sorted(rates.items()):
                    month_str = month_date.strftime("%Y-%m")
                    writer.writerow([month_str, str(rate)])

    def fetch_exchange_rates(self) -> None:
        self._load_existing_exchange_rates()
        session = requests.Session()
        for year in range(self.start_year, self.end_year + 1):
            for month in range(1, 13):
                month_date = datetime.date(year, month, 1)
                if month_date > datetime.date.today():
                    continue  # Don't fetch future dates

                # Check if rates already exist for this month
                if len(self.exchange_rates) > 0 and all(
                    month_date in rates for rates in self.exchange_rates.values()
                ):
                    continue  # Already have rates for this month

                if year < self.NEW_ENDPOINT_FROM_YEAR:
                    month_str = month_date.strftime("%m%y")
                    url = self.HMRC_OLD_URL_TEMPLATE.format(month_str=month_str)
                else:
                    month_str = month_date.strftime("%Y-%m")
                    url = self.HMRC_NEW_URL_TEMPLATE.format(month_str=month_str)

                response = session.get(url, timeout=20)
                # response.raise_for_status()
                if response.status_code != requests.codes.OK:
                    date_str = month_date.strftime("%Y-%m-%d")
                    print(f"Failed fetching data for {date_str}")
                    continue
                tree = ET.fromstring(response.text)
                rates = {
                    str(
                        getattr(row.find("currencyCode"), "text", None)
                    ).upper(): Decimal(str(getattr(row.find("rateNew"), "text", None)))
                    for row in tree
                }

                for currency, rate in rates.items():
                    if currency not in self.exchange_rates:
                        self.exchange_rates[currency] = {}
                    self.exchange_rates[currency][month_date] = rate

        # Save the fetched rates to files
        self._save_exchange_rates()


def _run() -> int:
    current_year = datetime.date.today().year
    start_year = current_year - 10
    end_year = current_year
    fetcher = FetchExchangeRates(
        start_year=start_year,
        end_year=end_year,
    )
    fetcher.fetch_exchange_rates()
    return 0


def run() -> None:
    sys.exit(_run())
