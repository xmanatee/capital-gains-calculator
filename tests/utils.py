"""Utils for tests."""

import sys


def build_cmd(*args: str) -> list[str]:
    """Return CLI command for cgt_calc without report generation."""
    return [sys.executable, "-m", "cgt_calc.main", *args, "--no-report"]
