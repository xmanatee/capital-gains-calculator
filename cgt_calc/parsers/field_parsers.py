"""Common field parsers for transaction files."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from cgt_calc.const import TICKER_RENAMES

ParsedFieldType = Any  # type: ignore[misc]
FieldParserType = Callable[[str], ParsedFieldType]


def decimal(val: str) -> Decimal:
    try:
        return Decimal(val.replace(",", ""))
    except InvalidOperation as err:
        raise ValueError(f"Invalid decimal value: {val}") from err


def dollar_amount(val: str, expect_dollar_sign=True) -> Decimal:
    if val == "0":
        return Decimal(val)
    if val.startswith(("$", "-$")):
        return decimal(val.replace("$", ""))

    if expect_dollar_sign:
        raise ValueError(f"Invalid dollar amount: {val}")

    return Decimal(val)


def symbol(val: str) -> str:
    return TICKER_RENAMES.get(val, val)


def _optional(
    val: str,
    parser: Callable[[str], ParsedFieldType],
    default: ParsedFieldType = None,
    none_values: Optional[list[str]] = None,
) -> ParsedFieldType:
    if none_values and val in none_values:
        return default
    return parser(val) if val != "" else default


def optional(
    parser: Callable[[str], ParsedFieldType],
    default: ParsedFieldType = None,
    none_values: Optional[list[str]] = None,
) -> Callable[[str], ParsedFieldType]:
    return lambda val: _optional(val, parser, default, none_values)


def date_format(format: str) -> Callable[[str], date]:
    return lambda val: datetime.strptime(val, format).date()


def _map(val: str, m: dict[str, str]) -> str:
    if val not in m:
        raise ValueError(f"Invalid value: {val}. Available keys: {m.keys()}")

    return m[val]


def const_map(m: dict[str, str]) -> Callable[[str], str]:
    return lambda val: _map(val, m)


def one_of(allowed_values: list[str]) -> Callable[[str], str]:
    m = {i: i for i in allowed_values}
    return lambda val: _map(val, m)


def const_value(const: str) -> Callable[[str], str]:
    return one_of([const])
