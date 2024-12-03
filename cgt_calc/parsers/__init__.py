"""Parse input files."""

from __future__ import annotations

from collections import defaultdict
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from cgt_calc.const import DEFAULT_INITIAL_PRICES_FILE
from cgt_calc.parsers.initial_prices import InitialPricesParser
from cgt_calc.parsers.mssb import read_mssb_transactions
from cgt_calc.parsers.raw import read_raw_transactions
from cgt_calc.parsers.schwab import read_schwab_transactions
from cgt_calc.parsers.schwab_equity_award_json import (
    read_schwab_equity_award_json_transactions,
)
from cgt_calc.parsers.sharesight import read_sharesight_transactions
from cgt_calc.parsers.trading212 import read_trading212_transactions
from cgt_calc.resources import RESOURCES_PACKAGE

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from cgt_calc.model import BrokerTransaction


def read_broker_transactions(
    schwab_transactions_file: str | None,
    schwab_awards_transactions_file: str | None,
    schwab_equity_award_json_transactions_file: str | None,
    trading212_transactions_folder: str | None,
    mssb_transactions_folder: str | None,
    sharesight_transactions_folder: str | None,
    raw_transactions_file: str | None,
) -> list[BrokerTransaction]:
    """Read transactions for all brokers."""
    transactions = []
    if schwab_transactions_file is not None:
        transactions += read_schwab_transactions(
            schwab_transactions_file, schwab_awards_transactions_file
        )
    else:
        print("INFO: No schwab file provided")

    if schwab_equity_award_json_transactions_file is not None:
        transactions += read_schwab_equity_award_json_transactions(
            schwab_equity_award_json_transactions_file
        )
    else:
        print("INFO: No schwab Equity Award JSON file provided")

    if trading212_transactions_folder is not None:
        transactions += read_trading212_transactions(trading212_transactions_folder)
    else:
        print("INFO: No trading212 folder provided")

    if mssb_transactions_folder is not None:
        transactions += read_mssb_transactions(mssb_transactions_folder)
    else:
        print("INFO: No mssb folder provided")

    if sharesight_transactions_folder is not None:
        transactions += read_sharesight_transactions(sharesight_transactions_folder)
    else:
        print("INFO: No sharesight file provided")

    if raw_transactions_file is not None:
        transactions += read_raw_transactions(raw_transactions_file)
    else:
        print("INFO: No raw file provided")

    transactions.sort(key=lambda k: k.date)
    return transactions


def read_initial_prices(
    initial_prices_file: str | None,
) -> dict[date, dict[str, Decimal]]:
    """Read initial stock prices from CSV file."""

    if initial_prices_file:
        date_symbol_price_list = InitialPricesParser().parse_file(
            Path(initial_prices_file)
        )
    else:
        traversable_res = resources.files(RESOURCES_PACKAGE).joinpath(
            DEFAULT_INITIAL_PRICES_FILE
        )
        with resources.as_file(traversable_res) as path:
            date_symbol_price_list = InitialPricesParser().parse_file(path)

    initial_prices: dict[date, dict[str, Decimal]] = defaultdict(dict)

    for date_, symbol, price in date_symbol_price_list:
        initial_prices[date_][symbol] = price
    return initial_prices
