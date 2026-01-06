"""Parse ERI input files.

Excess Reported Income are yearly reports provided by offshore fund managers
to HMRC for taxation purposes. They report for each fund the amount of excess
income that has to be reported for taxation purposes.

See: https://www.gov.uk/government/publications/offshore-funds-list-of-reporting-funds
"""

from __future__ import annotations

from importlib import resources
from typing import TYPE_CHECKING

from cgt_calc.const import ERI_RESOURCE_FOLDER
from cgt_calc.resources import RESOURCES_PACKAGE

from .raw import read_eri_raw

if TYPE_CHECKING:
    from pathlib import Path

    from cgt_calc.isin_converter import IsinConverter

    from .model import EriTransaction


def read_eri_transactions(
    isin_converter: IsinConverter,
    eri_raw_file: Path,
    include_bundled_resources: bool = False,
) -> list[EriTransaction]:
    """Read Excess Reported Income transactions for funds.

    Args:
        isin_converter: Converter to resolve ISINs to ticker symbols.
        eri_raw_file: User-provided ERI CSV file.
        include_bundled_resources: If True, also process bundled ERI resource files.

    """
    transactions: list[EriTransaction] = []

    if include_bundled_resources:
        resource_files = sorted(
            resources.files(RESOURCES_PACKAGE).joinpath(ERI_RESOURCE_FOLDER).iterdir(),
            key=lambda f: f.name,
        )
        for file in resource_files:
            if file.is_file() and file.name.endswith(".csv"):
                transactions += read_eri_raw(file, isin_converter)

    transactions += read_eri_raw(eri_raw_file, isin_converter)

    return transactions
