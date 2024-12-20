"""Unit and integration tests."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from cgt_calc.calculator import CapitalGainsCalculator
from cgt_calc.currency_converter import CurrencyConverter
from cgt_calc.current_price_fetcher import CurrentPriceFetcher
from cgt_calc.hmrc_transactions import HmrcTransactions
from cgt_calc.initial_prices import InitialPrices
from cgt_calc.spin_off_handler import SpinOffHandler
from cgt_calc.util import round_decimal

from .test_data.calc_test_data import calc_basic_data
from .test_data.calc_test_data_2 import calc_basic_data_2

if TYPE_CHECKING:
    from cgt_calc.model import BrokerTransaction, CalculationLog, CapitalGainsReport


def get_report(
    hmrc_transactions: HmrcTransactions,
    calculator: CapitalGainsCalculator,
    broker_transactions: list[BrokerTransaction],
) -> CapitalGainsReport:
    """Get calculation report."""
    hmrc_transactions.from_broker_transactions(broker_transactions)
    return calculator.calculate_capital_gain(hmrc_transactions)


@pytest.mark.parametrize(
    (
        "tax_year",
        "broker_transactions",
        "expected",
        "expected_unrealized",
        "current_prices",
        "calculation_log",
    ),
    calc_basic_data + calc_basic_data_2,
)
def test_basic(
    tax_year: int,
    broker_transactions: list[BrokerTransaction],
    expected: float,
    expected_unrealized: float | None,
    current_prices: dict[str, Decimal | None] | None,
    calculation_log: CalculationLog | None,
) -> None:
    """Generate basic tests for test data."""
    converter = CurrencyConverter(
        ["USD"], data_dir="tests/test_data/test_exchange_rates"
    )
    historical_prices = {
        "FOO": {datetime.date(day=5, month=7, year=2023): Decimal(90)},
        "BAR": {datetime.date(day=5, month=7, year=2023): Decimal(12)},
    }
    price_fetcher = CurrentPriceFetcher(converter, current_prices, historical_prices)
    spin_off_handler = SpinOffHandler()
    spin_off_handler.cache = {"BAR": "FOO"}
    initial_prices = InitialPrices({})
    hmrc_transactions = HmrcTransactions(
        tax_year,
        converter,
        price_fetcher,
        spin_off_handler,
        initial_prices,
    )
    calculator = CapitalGainsCalculator(
        tax_year,
        price_fetcher,
        calc_unrealized_gains=expected_unrealized is not None,
    )
    report = get_report(hmrc_transactions, calculator, broker_transactions)
    assert report.total_gain() == round_decimal(Decimal(expected), 2)
    print(str(report))
    if expected_unrealized is not None:
        assert report.total_unrealized_gains() == round_decimal(
            Decimal(expected_unrealized), 2
        )
    if calculation_log is not None:
        result_log = report.calculation_log
        assert len(result_log) == len(calculation_log)
        for date_index, expected_entries_map in calculation_log.items():
            assert date_index in result_log
            result_entries_map = result_log[date_index]
            print(date_index)
            print(result_entries_map)
            assert len(result_entries_map) == len(expected_entries_map)
            for entries_type, expected_entries_list in expected_entries_map.items():
                assert entries_type in result_entries_map
                result_entries_list = result_entries_map[entries_type]
                assert len(result_entries_list) == len(expected_entries_list)
                for i, expected_entry in enumerate(expected_entries_list):
                    result_entry = result_entries_list[i]
                    assert result_entry.rule_type == expected_entry.rule_type
                    assert result_entry.quantity == expected_entry.quantity
                    assert result_entry.new_quantity == expected_entry.new_quantity
                    assert round_decimal(
                        result_entry.new_pool_cost, 4
                    ) == round_decimal(expected_entry.new_pool_cost, 4)
                    assert round_decimal(result_entry.gain, 4) == round_decimal(
                        expected_entry.gain, 4
                    )
                    assert round_decimal(result_entry.amount, 4) == round_decimal(
                        expected_entry.amount, 4
                    )
                    assert round_decimal(
                        result_entry.allowable_cost, 4
                    ) == round_decimal(expected_entry.allowable_cost, 4)
                    assert (
                        result_entry.bed_and_breakfast_date_index
                        == expected_entry.bed_and_breakfast_date_index
                    )
                    assert round_decimal(result_entry.fees, 4) == round_decimal(
                        expected_entry.fees, 4
                    )


def test_run_with_example_files() -> None:
    """Runs the script and verifies it doesn't fail."""
    cmd = [
        sys.executable,
        "-m",
        "cgt_calc.main",
        "--year",
        "2020",
        "--schwab",
        "tests/test_data/schwab_transactions.csv",
        "--trading212",
        "tests/test_data/trading212/",
        "--mssb",
        "tests/test_data/mssb/",
        "--no-pdflatex",
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(e.stderr.decode("utf-8"))
        raise

    assert result.returncode == 0
    assert result.stderr == b"", "Run with example files generated errors"
    expected_file = (
        Path("tests") / "test_data" / "test_run_with_example_files_output.txt"
    )
    expected = expected_file.read_text()
    cmd_str = " ".join([param if param else "''" for param in cmd])
    assert result.stdout.decode("utf-8") == expected, (
        "Run with example files generated unexpected outputs, "
        "if you added new features update the test with:\n"
        f"{cmd_str} > {expected_file}"
    )
