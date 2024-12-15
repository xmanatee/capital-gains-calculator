from __future__ import annotations

from dataclasses import InitVar, dataclass
import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Final

from cgt_calc.const import TICKER_RENAMES
from cgt_calc.exceptions import ParsingError
from cgt_calc.model import BrokerSource, BrokerTransaction
from cgt_calc.util import round_decimal
from cgt_calc.parsers.schwab import parse_schwab_action
import cgt_calc.parsers.field_parsers as parse

OPTIONAL_DETAILS_NAME: Final = "Details"
FIELD_TO_SCHEMA: Final = {"transactions": 1, "Transactions": 2}


@dataclass
class FieldNames:
    """Names of the fields in the Schwab JSON data, depending on the schema version."""

    # Note that the schema version is not an official Schwab one, just something
    # we use internally in this code:
    schema_version: InitVar[int] = 2

    transactions: str = "Transactions"
    description: str = "Description"
    action: str = "Action"
    symbol: str = "Symbol"
    quantity: str = "Quantity"
    amount: str = "Amount"
    fees: str = "FeesAndCommissions"
    transac_details: str = "TransactionDetails"
    shares: str = "Shares"
    vest_date: str = "VestDate"
    vest_fair_market_value: str = "VestFairMarketValue"
    award_date: str = "AwardDate"
    award_id: str = "AwardId"
    date: str = "Date"
    sale_price: str = "SalePrice"

    def __post_init__(self, schema_version: int) -> None:
        """Set correct field names if the schema is not the default one.

        Automatically run on object initialization.
        """
        if schema_version == 1:
            self.transactions = "transactions"
            self.description = "description"
            self.action = "action"
            self.symbol = "symbol"
            self.quantity = "quantity"
            self.amount = "amount"
            self.fees = "totalCommissionsAndFees"
            self.transac_details = "transactionDetails"
            self.shares = "shares"
            self.vest_date = "vestDate"
            self.vest_fair_market_value = "vestFairMarketValue"
            self.award_date = "awardDate"
            self.award_id = "awardName"
            self.date = "eventDate"
            self.sale_price = "salePrice"


# We want enough decimals to cover what Schwab gives us (up to 4 decimals)
# divided by the share-split factor (20), so we keep 6 decimals.
# We don't want more decimals than necessary or we risk converting
# the float number format approximations into Decimals
# (e.g. a number 1.0001 in JSON may become 1.00010001 when parsed
# into float, but we want to get Decimal('1.0001'))
ROUND_DIGITS = 6

JsonRowType = Any  # type: ignore[misc]


def _decimal_from_number_or_str(
    row: JsonRowType,
    field_basename: str,
    field_float_suffix: str = "SortValue",
) -> Decimal:
    """Get a number from a row, preferably from the number field.

    Fall back to the string representation field, or default to Decimal(0)
    if the fields are not there or both have a value of None.
    """
    # We prefer native number to strings as more efficient/safer parsing
    float_name = f"{field_basename}{field_float_suffix}"
    if float_name in row and row[float_name] is not None:
        return Decimal(row[float_name])

    if field_basename in row and row[field_basename] is not None:
        return parse.dollar_amount(
            row[field_basename],
            expect_dollar_sign=False)

    return Decimal(0)


def _is_integer(number: Decimal) -> bool:
    return number % 1 == 0


class SchwabTransaction(BrokerTransaction):
    """Represent single Schwab transaction."""

    def __init__(self, row: JsonRowType, file: str, field_names: FieldNames) -> None:
        """Create a new SchwabTransaction from a JSON row."""
        names = field_names
        description = row[names.description]
        self.raw_action = row[names.action]
        action = parse_schwab_action(self.raw_action)
        symbol = row.get(names.symbol)
        symbol = TICKER_RENAMES.get(symbol, symbol)
        if symbol != "GOOG":
            # Stock split hardcoded for GOOG
            raise ParsingError(
                file,
                f"Schwab Equity Award JSON only supports GOOG stock but found {symbol}",
            )
        quantity = _decimal_from_number_or_str(row, names.quantity)
        amount = _decimal_from_number_or_str(row, names.amount)
        fees = _decimal_from_number_or_str(row, names.fees)
        if row[names.action] == "Deposit":
            if len(row[names.transac_details]) != 1:
                raise ParsingError(
                    file,
                    "Expected a single Transaction Details for a Deposit, but "
                    f"found {len(row[names.transac_details])}",
                )
            if OPTIONAL_DETAILS_NAME in row[names.transac_details][0]:
                details = row[names.transac_details][0]["Details"]
            else:
                details = row[names.transac_details][0]
            date = datetime.datetime.strptime(
                details[names.vest_date], "%m/%d/%Y"
            ).date()
            # Schwab only provide this one as string:
            price = parse.dollar_amount(
                details[names.vest_fair_market_value],
                expect_dollar_sign=False)
            if amount == Decimal(0):
                amount = price * quantity
            description = (
                f"Vest from Award Date "
                f"{details[names.award_date]} "
                f"(ID {details[names.award_id]})"
            )
        elif row[names.action] == "Sale":
            date = datetime.datetime.strptime(row[names.date], "%m/%d/%Y").date()

            # Schwab's data export sometimes lacks decimals on Sales
            # quantities, in which case we infer it from number of shares in
            # sub-transactions, or failing that from the amount and salePrice.
            if not _is_integer(quantity):
                price = (amount + fees) / quantity
            else:
                subtransac_have_quantities = True
                subtransac_shares_sum = Decimal()  # Decimal 0
                found_share_decimals = False

                details = row[names.transac_details][0].get(
                    OPTIONAL_DETAILS_NAME, row[names.transac_details][0]
                )

                for subtransac in row[names.transac_details]:
                    subtransac = subtransac.get(OPTIONAL_DETAILS_NAME, subtransac)

                    if "shares" in subtransac:
                        # Schwab only provides this one as a string:
                        shares = parse.dollar_amount(
                            subtransac[names.shares],
                            expect_dollar_sign=False)
                        subtransac_shares_sum += shares
                        if not _is_integer(shares):
                            found_share_decimals = True
                    else:
                        subtransac_have_quantities = False
                        break

                if subtransac_have_quantities and found_share_decimals:
                    quantity = subtransac_shares_sum
                    price = (amount + fees) / quantity
                else:
                    # Schwab sometimes only gives us overall transaction
                    # amount, and sale price of the sub-transactions.
                    # We can only work-out the correct quantity if all
                    # sub-transactions have the same price:

                    first_subtransac = row[names.transac_details][0]
                    first_subtransac = first_subtransac.get(
                        OPTIONAL_DETAILS_NAME, first_subtransac
                    )
                    price_str = first_subtransac[names.sale_price]
                    price = parse.dollar_amount(
                        price_str,
                        expect_dollar_sign=False)

                    for subtransac in row[names.transac_details][1:]:
                        subtransac = subtransac.get(OPTIONAL_DETAILS_NAME, subtransac)

                        if subtransac[names.sale_price] != price_str:
                            raise ParsingError(
                                file,
                                "Impossible to work out quantity of sale of "
                                f"date {date} and amount {amount} because "
                                "different sub-transaction have different sale"
                                " prices",
                            )

                    quantity = (amount + fees) / price
        else:
            date = datetime.datetime.strptime(row[names.date], "%m/%d/%Y").date()
            price = None
            print(
                f"WARNING: Parsing for action {row[names.action]} is not implemented!"
            )
            # raise ParsingError(
            #     file, f"Parsing for action {row[names.action]} is not implemented!"
            # )

        super().__init__(
            date,
            action,
            symbol,
            description,
            quantity,
            price,
            fees,
            amount,
            "USD",
            BrokerSource.SCHWAB_AWARDS,
        )

        self._normalize_split()

    def _normalize_split(self) -> None:
        """Ensure past transactions are normalized to split values.

        This is in the context of the 20:1 GOOG stock split which happened at
        close on 2022-07-15 20:1.

        As of 2022-08-07, Schwab's data exports have some past transactions
        corrected for the 20:1 split on 2022-07-15, whereas others are not.
        """
        split_factor = 20
        threshold_price = 175

        # The share price has never been above $175*20=$3500 before 2022-07-15
        # so this price is expressed in pre-split amounts: normalize to post-split
        if (
            self.date <= datetime.date(2022, 7, 15)
            and self.price
            and self.price > threshold_price
            and self.quantity
        ):
            self.price = round_decimal(self.price / split_factor, ROUND_DIGITS)
            self.quantity = round_decimal(self.quantity * split_factor, ROUND_DIGITS)


def read_schwab_equity_award_json_transactions(
    transactions_file: str,
) -> list[BrokerTransaction]:
    """Read Schwab transactions from file."""
    with Path(transactions_file).open(encoding="utf-8") as json_file:
        try:
            data = json.load(json_file, parse_float=Decimal, parse_int=Decimal)
        except json.decoder.JSONDecodeError as exception:
            raise ParsingError(
                transactions_file,
                "Cloud not parse content as JSON",
            ) from exception

        for field_name, schema_version in FIELD_TO_SCHEMA.items():
            if field_name in data:
                fields = FieldNames(schema_version)
                break
        if not fields:
            raise ParsingError(
                transactions_file,
                f"Expected top level field ({', '.join(FIELD_TO_SCHEMA.keys())}) "
                "not found: the JSON data is not in the expected format",
            )

        if not isinstance(data[fields.transactions], list):
            raise ParsingError(
                transactions_file,
                f"'{fields.transactions}' is not a list: the JSON data is not "
                "in the expected format",
            )

        transactions = [
            SchwabTransaction(transac, transactions_file, fields)
            for transac in data[fields.transactions]
            # Skip as not relevant for CGT
            if transac[fields.action] not in {"Journal", "Wire Transfer"}
        ]
        transactions.reverse()
        return list(transactions)
