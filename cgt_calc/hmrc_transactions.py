from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import logging
from typing import TYPE_CHECKING

from cgt_calc.dates import get_tax_year_end, get_tax_year_start, is_date
from cgt_calc.exceptions import (
    AmountMissingError,
    CalculatedAmountDiscrepancyError,
    CalculationError,
    InvalidTransactionError,
    PriceMissingError,
    QuantityNotPositiveError,
    SymbolMissingError,
)
from cgt_calc.model import (
    ActionType,
    Broker,
    BrokerTransaction,
    HmrcTransactionLog,
    Position,
    SpinOff,
)
from cgt_calc.transaction_log import add_to_list
from cgt_calc.util import round_decimal

if TYPE_CHECKING:
    import datetime

    from cgt_calc.currency_converter import CurrencyConverter
    from cgt_calc.current_price_fetcher import CurrentPriceFetcher
    from cgt_calc.initial_prices import InitialPrices
    from cgt_calc.spin_off_handler import SpinOffHandler

LOGGER = logging.getLogger(__name__)


def get_amount_or_fail(transaction: BrokerTransaction) -> Decimal:
    """Return the transaction amount or throw an error."""
    amount = transaction.amount
    if amount is None:
        raise AmountMissingError(transaction)
    return amount


# It is not clear how Schwab or other brokers round the dollar value,
# so assume the values are equal if they are within $0.10.
def _approx_equal(val_a: Decimal, val_b: Decimal) -> bool:
    return abs(val_a - val_b) < Decimal("0.10")


class HmrcTransactions:
    def __init__(
        self,
        tax_year: int,
        converter: CurrencyConverter,
        price_fetcher: CurrentPriceFetcher,
        spin_off_handler: SpinOffHandler,
        initial_prices: InitialPrices,
        balance_check: bool = True,
    ):
        """Create calculator object."""
        self.tax_year = tax_year

        self.tax_year_start_date = get_tax_year_start(tax_year)
        self.tax_year_end_date = get_tax_year_end(tax_year)

        self.converter = converter
        self.price_fetcher = price_fetcher
        self.spin_off_handler = spin_off_handler
        self.initial_prices = initial_prices
        self.balance_check = balance_check

        self.acquisition_list: HmrcTransactionLog = {}
        self.disposal_list: HmrcTransactionLog = {}

        self.portfolio: dict[str, Position] = defaultdict(Position)
        self.spin_offs: dict[datetime.date, list[SpinOff]] = defaultdict(list)

    def _date_in_tax_year(self, date: datetime.date) -> bool:
        """Check if date is within current tax year."""
        assert is_date(date)
        return self.tax_year_start_date <= date <= self.tax_year_end_date

    def _add_acquisition(
        self,
        transaction: BrokerTransaction,
    ) -> None:
        """Add new acquisition to the given list."""
        symbol = transaction.symbol
        quantity = transaction.quantity
        price = transaction.price

        if symbol is None:
            raise SymbolMissingError(transaction)
        if quantity is None or quantity <= 0:
            raise QuantityNotPositiveError(transaction)

        # Add to acquisition_list to apply same day rule
        if transaction.action is ActionType.STOCK_ACTIVITY:
            if price is None:
                price = self.initial_prices.get(transaction.date, symbol)
            amount = round_decimal(quantity * price, 2)
        elif transaction.action is ActionType.SPIN_OFF:
            price, amount = self._handle_spin_off(transaction)
        elif transaction.action is ActionType.STOCK_SPLIT:
            price = Decimal(0)
            amount = Decimal(0)
        else:
            if price is None:
                raise PriceMissingError(transaction)

            amount = get_amount_or_fail(transaction)
            calculated_amount = quantity * price + transaction.fees
            if not _approx_equal(amount, -calculated_amount):
                raise CalculatedAmountDiscrepancyError(transaction, -calculated_amount)
            amount = -amount

        self.portfolio[symbol] += Position(quantity, amount)

        add_to_list(
            self.acquisition_list,
            transaction.date,
            symbol,
            quantity,
            self.converter.to_gbp_for(amount, transaction),
            self.converter.to_gbp_for(transaction.fees, transaction),
        )

    def _handle_spin_off(
        self,
        transaction: BrokerTransaction,
    ) -> tuple[Decimal, Decimal]:
        """Handle spin off transaction.

        Doc basing on SOLV spin off out of MMM.

        # 1. Determine the Cost Basis (Acquisition Cost) of the SOLV Shares
        In the UK, the cost basis (or acquisition cost) of the new SOLV shares
        received from the spin-off needs to be determined. This is usually done
        by apportioning part of the original cost basis of the MMM shares to
        the new SOLV shares based on their market values at the time of the
        spin-off.

        ## Step-by-Step Allocation
        * Find the Market Values:

        Determine the market value of MMM shares and SOLV shares immediately
        after the spin-off.

        * Calculate the Apportionment:

        Divide the market value of the MMM shares by the total market value of
        both MMM and SOLV shares to find the percentage allocated to MMM.
        Do the same for SOLV shares to find the percentage allocated to SOLV.

        * Allocate the Original Cost Basis:

        Multiply the original cost basis of your MMM shares by the respective
        percentages to allocate the cost basis between the MMM and SOLV shares.

        ## Example Allocation
        * Original Investment:

        Assume you bought 100 shares of MMM at £100 per share, so your total
        cost basis is £10,000.

        * Market Values Post Spin-off:

        Assume the market value of MMM shares is £90 per share and SOLV shares
        is £10 per share immediately after the spin-off.
        The total market value is £90 + £10 = £100.

        * Allocation Percentages:

        Percentage allocated to MMM: 90/100 = 90%
        Percentage allocated to SOLV: 10/100 = 10%

        * Allocate Cost Basis:

        Cost basis of MMM: £10,000 * 0.90 = £9,000
        Cost basis of SOLV: £10,000 * 0.10 = £1,000

        # 2. Determine the Holding Period
        The holding period for the SOLV shares typically includes the holding
        period of the original MMM shares. This means the date you acquired the
        MMM shares will be used as the acquisition date for the SOLV shares.
        """
        symbol = transaction.symbol
        quantity = transaction.quantity
        assert symbol is not None
        assert quantity is not None

        ticker = self.spin_off_handler.get_spin_off_source(
            symbol, transaction.date, self.portfolio
        )
        dst_price = self.price_fetcher.get_closing_price(symbol, transaction.date)
        src_price = self.price_fetcher.get_closing_price(ticker, transaction.date)
        dst_amount = quantity * dst_price
        src_amount = self.portfolio[ticker].quantity * src_price
        original_src_amount = self.portfolio[ticker].amount

        share_of_original_cost = src_amount / (dst_amount + src_amount)
        self.spin_offs[transaction.date].append(
            SpinOff(
                dest=symbol,
                source=ticker,
                cost_proportion=share_of_original_cost,
                date=transaction.date,
            )
        )

        amount = (1 - share_of_original_cost) * original_src_amount
        return amount / quantity, round_decimal(amount, 2)

    def _add_disposal(
        self,
        transaction: BrokerTransaction,
    ) -> None:
        """Add new disposal to the given list."""
        symbol = transaction.symbol
        quantity = transaction.quantity
        if symbol is None:
            raise SymbolMissingError(transaction)
        if symbol not in self.portfolio:
            raise InvalidTransactionError(
                transaction, "Tried to sell not owned symbol, reversed order?"
            )
        if quantity is None or quantity <= 0:
            raise QuantityNotPositiveError(transaction)
        if self.portfolio[symbol].quantity < quantity:
            raise InvalidTransactionError(
                transaction,
                "Tried to sell more than the available "
                f"balance({self.portfolio[symbol].quantity})",
            )

        amount = get_amount_or_fail(transaction)
        price = transaction.price

        self.portfolio[symbol] -= Position(quantity, amount)

        if self.portfolio[symbol].quantity == 0:
            del self.portfolio[symbol]

        if price is None:
            raise PriceMissingError(transaction)
        calculated_amount = quantity * price - transaction.fees
        if not _approx_equal(amount, calculated_amount):
            raise CalculatedAmountDiscrepancyError(transaction, calculated_amount)
        add_to_list(
            self.disposal_list,
            transaction.date,
            symbol,
            quantity,
            self.converter.to_gbp_for(amount, transaction),
            self.converter.to_gbp_for(transaction.fees, transaction),
        )

    def from_broker_transactions(
        self,
        transactions: list[BrokerTransaction],
    ) -> None:
        """Convert broker transactions to HMRC transactions."""
        # We keep a balance per broker,currency pair
        balance: dict[tuple[Broker, str], Decimal] = defaultdict(lambda: Decimal(0))
        dividends = Decimal(0)
        dividends_tax = Decimal(0)
        interest = Decimal(0)
        total_sells = Decimal(0)
        balance_history: list[Decimal] = []

        for i, transaction in enumerate(transactions):
            new_balance = balance[
                (transaction.broker_source.broker, transaction.currency)
            ]
            if transaction.action is ActionType.TRANSFER:
                new_balance += get_amount_or_fail(transaction)
            elif transaction.action in [
                ActionType.BUY,
                ActionType.REINVEST_SHARES,
            ]:
                new_balance += get_amount_or_fail(transaction)
                self._add_acquisition(transaction)
            elif transaction.action in [ActionType.SELL, ActionType.CASH_MERGER]:
                amount = get_amount_or_fail(transaction)
                new_balance += amount
                self._add_disposal(transaction)
                if self._date_in_tax_year(transaction.date):
                    total_sells += self.converter.to_gbp_for(amount, transaction)
            elif transaction.action is ActionType.FEE:
                amount = get_amount_or_fail(transaction)
                new_balance += amount
                transaction.fees = -amount
                transaction.quantity = Decimal(0)
                gbp_fees = self.converter.to_gbp_for(transaction.fees, transaction)
                if transaction.symbol is None:
                    raise SymbolMissingError(transaction)
                add_to_list(
                    self.acquisition_list,
                    transaction.date,
                    transaction.symbol,
                    transaction.quantity,
                    gbp_fees,
                    gbp_fees,
                )
            elif transaction.action in [
                ActionType.STOCK_ACTIVITY,
                ActionType.SPIN_OFF,
                ActionType.STOCK_SPLIT,
            ]:
                self._add_acquisition(transaction)
            elif transaction.action in [ActionType.DIVIDEND, ActionType.CAPITAL_GAIN]:
                amount = get_amount_or_fail(transaction)
                new_balance += amount
                if self._date_in_tax_year(transaction.date):
                    dividends += self.converter.to_gbp_for(amount, transaction)
            elif transaction.action in [ActionType.TAX, ActionType.ADJUSTMENT]:
                amount = get_amount_or_fail(transaction)
                new_balance += amount
                if self._date_in_tax_year(transaction.date):
                    dividends_tax += self.converter.to_gbp_for(amount, transaction)
            elif transaction.action is ActionType.INTEREST:
                amount = get_amount_or_fail(transaction)
                new_balance += amount
                if self._date_in_tax_year(transaction.date):
                    interest += self.converter.to_gbp_for(amount, transaction)
            elif transaction.action is ActionType.WIRE_FUNDS_RECEIVED:
                amount = get_amount_or_fail(transaction)
                new_balance += amount
            elif transaction.action is ActionType.REINVEST_DIVIDENDS:
                print(f"WARNING: Ignoring unsupported action: {transaction.action}")
            else:
                raise InvalidTransactionError(
                    transaction, f"Action not processed({transaction.action})"
                )
            balance_history.append(new_balance)
            if self.balance_check and new_balance < 0:
                msg = (
                    f"Reached a negative balance({new_balance}) for broker "
                    f"'{transaction.broker_source.broker.readable_name}' "
                    f"({transaction.currency}) after processing the following "
                    "transactions:\n"
                )
                msg += "\n".join(
                    [
                        f"{trx}\nBalance after transaction={balance_after}"
                        for trx, balance_after in zip(
                            transactions[: i + 1], balance_history
                        )
                    ]
                )
                raise CalculationError(msg)
            balance[(transaction.broker_source.broker, transaction.currency)] = (
                new_balance
            )
        print("First pass completed")
        print("Final portfolio:")
        for stock, position in self.portfolio.items():
            print(f"  {stock}: {position}")
        print("Final balance:")
        for (broker, currency), amount in balance.items():
            print(f"  {broker.readable_name}: {round_decimal(amount, 2)} ({currency})")
        print(f"Dividends: £{round_decimal(dividends, 2)}")
        print(f"Dividend taxes: £{round_decimal(-dividends_tax, 2)}")
        print(f"Interest: £{round_decimal(interest, 2)}")
        print(f"Disposal proceeds: £{round_decimal(total_sells, 2)}")
        print()
