#!/usr/bin/env python3
"""Capital Gain Calculator main module."""

from __future__ import annotations

import decimal
import importlib.metadata
import logging
from pathlib import Path
import sys

from cgt_calc.calculator import CapitalGainsCalculator
from cgt_calc.hmrc_transactions import HmrcTransactions

from . import render_latex
from .args_parser import create_parser
from .currency_converter import CurrencyConverter
from .current_price_fetcher import CurrentPriceFetcher
from .initial_prices import InitialPrices
from .parsers import read_broker_transactions, read_initial_prices
from .spin_off_handler import SpinOffHandler

LOGGER = logging.getLogger(__name__)


def main() -> int:
    """Run main function."""
    # Throw exception on accidental float usage
    decimal.getcontext().traps[decimal.FloatOperation] = True
    args = create_parser().parse_args()

    if args.version:
        print(f"cgt-calc {importlib.metadata.version(__package__)}")
        return 0

    if args.report == "":
        print("error: report name can't be empty")
        return 1

    default_logging_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=default_logging_level)

    # Read data from input files
    broker_transactions = read_broker_transactions(
        args.schwab,
        args.schwab_award,
        args.schwab_equity_award_json,
        args.trading212,
        args.mssb,
        args.sharesight,
        args.raw,
    )
    converter = CurrencyConverter(["USD", "AUD", "RUB", "CNY", "INR"])
    initial_prices = InitialPrices(read_initial_prices(args.initial_prices))
    price_fetcher = CurrentPriceFetcher(converter)
    spin_off_handler = SpinOffHandler(args.spin_offs_file)

    hmrc_transactions = HmrcTransactions(
        args.year,
        converter,
        price_fetcher,
        spin_off_handler,
        initial_prices,
        balance_check=args.balance_check,
    )

    calculator = CapitalGainsCalculator(
        args.year,
        price_fetcher,
        calc_unrealized_gains=args.calc_unrealized_gains,
    )
    # First pass converts broker transactions to HMRC transactions.
    # This means applying same day rule and collapsing all transactions with
    # same type within the same day.
    # It also converts prices to GBP, validates data and calculates dividends,
    # taxes on dividends and interest.
    hmrc_transactions.from_broker_transactions(broker_transactions)

    # Second pass calculates capital gain tax for the given tax year.
    report = calculator.calculate_capital_gain(hmrc_transactions)
    print(report)

    # Generate PDF report.
    if not args.no_report:
        render_latex.render_calculations(
            report,
            output_path=Path(args.report),
            skip_pdflatex=args.no_pdflatex,
        )
    print("All done!")

    return 0


def init() -> None:
    sys.exit(main())


if __name__ == "__main__":
    init()
