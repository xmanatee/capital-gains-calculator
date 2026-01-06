"""Regression test for Schwab rounding edge cases."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_run_with_schwab_2023_rounding_file() -> None:
    """Runs the script and verifies it doesn't fail on rounding edge cases."""
    cmd = [
        sys.executable,
        "-m",
        "cgt_calc.main",
        "--year",
        "2023",
        "--schwab",
        "tests/test_data/schwab/schwab_transactions-2023.csv",
        "--no-pdflatex",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True)
    expected_file = Path("tests") / "test_data" / "schwab" / "expected_output.txt"
    expected = expected_file.read_text()
    cmd_str = " ".join([param if param else "''" for param in cmd])
    assert result.stdout.decode("utf-8") == expected, (
        "Run with Schwab rounding fixture generated unexpected outputs, "
        "if you changed output update the test with:\n"
        f"{cmd_str} > {expected_file}"
    )
