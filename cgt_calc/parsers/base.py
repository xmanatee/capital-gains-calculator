"""Base classes and functions for parsers."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
import csv
from pathlib import Path
from typing import Any

from cgt_calc.model import BrokerSource
from cgt_calc.parsers.field_parsers import ParsedFieldType

ParsedRowType = Any  # type: ignore[misc]


class Column:
    def __init__(self, csv_name: str, parser: Callable[[str], ParsedFieldType]):
        self.csv_name = csv_name
        self.parser = parser

    def is_present(self, headers: set[str]) -> bool:
        return self.csv_name in headers

    def remove_from(self, headers: set[str]) -> None:
        headers.remove(self.csv_name)

    def parse(self, row: dict[str, str]) -> dict[str, ParsedFieldType]:
        return {self.csv_name: self.parser(row[self.csv_name])}


class CsvParser(ABC):
    @abstractmethod
    def required_columns(self) -> list[Column]:
        raise NotImplementedError

    @abstractmethod
    def parse_row(
        self, row: dict[str, ParsedFieldType], raw_row: dict[str, str]
    ) -> ParsedRowType:
        raise NotImplementedError

    def check_columns(self, file: Path) -> tuple[list[str], list[str]]:
        with file.open(encoding="utf-8") as csv_file:
            reader = csv.reader(csv_file)
            headers = set(next(reader))

            unexpected = headers.copy()
            missing = set()
            for col in self.required_columns():
                if not col.is_present(headers):
                    missing.add(col.csv_name)
                else:
                    col.remove_from(unexpected)
            return list(unexpected), list(missing)

    def can_parse(self, file: Path) -> bool:
        _, missing = self.check_columns(file)
        return not missing

    def parse_file(self, file: Path) -> list[ParsedRowType]:
        with file.open(encoding="utf-8") as csv_file:
            reader = csv.reader(csv_file)
            headers = next(reader)
            return self.parse_rows(headers, reader)

    def parse_rows(
        self, headers: list[str], row_values_list: Iterable[list[str]]
    ) -> list[ParsedRowType]:
        transactions = []
        for row_values in row_values_list:
            if not any(row_values):
                continue
            row = dict(zip(headers, row_values))
            parsed_row = {}
            for col in self.required_columns():
                parsed_row.update(col.parse(row))
            transaction = self.parse_row(parsed_row, row)
            transactions.append(transaction)
        return transactions


class CsvTransactionParser(CsvParser):
    broker_source: BrokerSource = BrokerSource.UNKNOWN
