"""Charles Schwab parser."""

from __future__ import annotations

from collections import defaultdict
import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final

from cgt_calc.exceptions import ParsingError
from cgt_calc.model import ActionType, BrokerSource, BrokerTransaction
from cgt_calc.parsers.base import Column, CsvParser
import cgt_calc.parsers.field_parsers as parse

if TYPE_CHECKING:
    from cgt_calc.parsers.field_parsers import ParsedFieldType


def parse_schwab_action(label: str) -> ActionType:
    """Convert string label to ActionType."""
    if label in {"Buy"}:
        return ActionType.BUY
    if label in {"Sell"}:
        return ActionType.SELL
    if label in {
        "MoneyLink Transfer",
        "Misc Cash Entry",
        "Service Fee",
        "Wire Funds",
        "Wire Sent",
        "Funds Received",
        "Journal",
        "Cash In Lieu",
    }:
        return ActionType.TRANSFER
    if label in {"Stock Plan Activity"}:
        return ActionType.STOCK_ACTIVITY
    if label in [
        "Qualified Dividend",
        "Cash Dividend",
        "Qual Div Reinvest",
        "Div Adjustment",
        "Special Qual Div",
        "Non-Qualified Div",
    ]:
        return ActionType.DIVIDEND
    if label in {"NRA Tax Adj", "NRA Withholding", "Foreign Tax Paid"}:
        return ActionType.TAX
    if label in {"ADR Mgmt Fee"}:
        return ActionType.FEE
    if label in {"Adjustment", "IRS Withhold Adj", "Wire Funds Adj"}:
        return ActionType.ADJUSTMENT
    if label in {"Short Term Cap Gain", "Long Term Cap Gain"}:
        return ActionType.CAPITAL_GAIN
    if label == "Spin-off":
        return ActionType.SPIN_OFF
    if label in {"Credit Interest", "Bank Interest"}:
        return ActionType.INTEREST
    if label in {"Reinvest Shares"}:
        return ActionType.REINVEST_SHARES
    if label in {"Reinvest Dividend"}:
        return ActionType.REINVEST_DIVIDENDS
    if label in {"Wire Funds Received"}:
        return ActionType.WIRE_FUNDS_RECEIVED
    if label in {"Stock Split"}:
        return ActionType.STOCK_SPLIT
    if label in {"Cash Merger", "Cash Merger Adj"}:
        return ActionType.CASH_MERGER

    print(f"Unrecognized action in 'Schwab Transactions': {label}")
    return ActionType.UNKNOWN


def parse_schwab_date(date_str: str) -> datetime.date:
    as_of_str = " as of "
    if as_of_str in date_str:
        date_str = date_str.split(as_of_str)[0]
    return datetime.datetime.strptime(date_str, "%m/%d/%Y").date()


class SchwabTransaction(BrokerTransaction):
    def __init__(
        self,
        date: datetime.date,
        action: ActionType,
        symbol: str | None,
        description: str,
        quantity: Decimal | None,
        price: Decimal | None,
        fees: Decimal,
        amount: Decimal | None,
        raw_action: str,
    ):
        super().__init__(
            date=date,
            action=action,
            symbol=symbol,
            description=description,
            quantity=quantity,
            price=price,
            fees=fees,
            amount=amount,
            currency="USD",
            broker_source=BrokerSource.SCHWAB_INDIVIDUAL,
        )
        self.raw_action = raw_action


SCHWAB_CSV_COLUMNS: Final[list[Column]] = [
    Column("Date", parse_schwab_date),
    Column("Action", parse_schwab_action),
    Column("Symbol", parse.optional(parse.symbol)),
    Column("Description", parse.optional(str)),
    Column("Quantity", parse.optional(parse.decimal)),
    Column("Price", parse.optional(parse.dollar_amount)),
    Column("Fees & Comm", parse.optional(parse.dollar_amount)),
    Column("Amount", parse.optional(parse.dollar_amount)),
]


class SchwabParser(CsvParser):
    """Parser for Charles Schwab transactions."""

    def required_columns(self) -> list[Column]:
        return SCHWAB_CSV_COLUMNS

    def parse_row(
        self, row: dict[str, ParsedFieldType], raw_row: dict[str, str]
    ) -> SchwabTransaction:
        description=row["Description"] or ""
        raw_action = raw_row["Action"]
        if row["Action"] == ActionType.UNKNOWN:
            description = f"Unknown action: {raw_action}\n{description}"
        return SchwabTransaction(
            date=row["Date"],
            action=row["Action"],
            symbol=row["Symbol"],
            description=description,
            quantity=row["Quantity"],
            price=row["Price"],
            fees=row["Fees & Comm"] or Decimal(0),
            amount=row["Amount"],
            raw_action=raw_action,
        )

    def parse_file(self, file: Path) -> list[BrokerTransaction]:
        transactions = super().parse_file(file)
        # Handle "Rule 10b5-1 Trading Plan":
        auto_sell_prices: dict[datetime.date, dict[str, str]] = defaultdict(dict)
        for tx in transactions:
            if tx.action == ActionType.SELL:
                auto_sell_prices[tx.date][tx.symbol] = tx.price
        for tx in transactions:
            if tx.action == ActionType.STOCK_ACTIVITY and tx.price is None:
                if not tx.symbol:
                    raise ParsingError(str(file), "Missing symbol in stock activity")
                if tx.symbol not in auto_sell_prices[tx.date]:
                    print(
                        "WARNING: Leaving price blank for STOCK_ACTIVITY action "
                        f"from {tx.date} for {tx.symbol}"
                    )
                    continue
                tx.price = auto_sell_prices[tx.date][tx.symbol]

        transactions = self.unify_cash_merger_transactions(transactions)
        transactions.reverse()

        # Calling list() constructor to satisfy type requirements
        return list(transactions)

    def unify_cash_merger_transactions(
        self,
        transactions: list[SchwabTransaction],
    ) -> list[SchwabTransaction]:
        filtered: list[SchwabTransaction] = []
        for transaction in transactions:
            if transaction.raw_action == "Cash Merger Adj":
                if not filtered:
                    raise ParsingError(
                        "schwab", "Cash Merger Adj without preceding Cash Merger"
                    )
                prev_transaction = filtered[-1]
                if (
                    prev_transaction.raw_action != "Cash Merger"
                    or prev_transaction.description != transaction.description
                    or prev_transaction.symbol != transaction.symbol
                    or prev_transaction.date != transaction.date
                ):
                    raise ParsingError(
                        "schwab", "Cash Merger Adj does not match previous transaction"
                    )
                assert transaction.quantity is not None
                prev_transaction.quantity = -transaction.quantity
                prev_transaction.price = self._price(prev_transaction)
                prev_transaction.fees += transaction.fees
                print(
                    "WARNING: Cash Merger support is not complete and doesn't cover "
                    "the cases when shares are received aside from cash,  please "
                    "review this transaction carefully: "
                    f"{prev_transaction}"
                )
            else:
                filtered.append(transaction)
        return filtered

    def _price(self, tx: SchwabTransaction) -> Decimal:
        if tx.amount is None or tx.fees is None or tx.quantity is None:
            raise ValueError(
                "Smth is wrong with transaction: "
                f"{tx.amount}, {tx.fees}, {tx.quantity}"
            )

        return (tx.amount + tx.fees) / tx.quantity


def read_schwab_transactions(
    transactions_file: str, schwab_award_transactions_file: str | None = None
) -> list[BrokerTransaction]:
    """Read Schwab transactions from file."""
    return SchwabParser().parse_file(Path(transactions_file))
