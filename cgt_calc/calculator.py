#!/usr/bin/env python3
"""Capital Gain Calculator main module."""

from __future__ import annotations

from collections import defaultdict
import datetime
from decimal import Decimal
import logging
from typing import TYPE_CHECKING

from cgt_calc.const import (
    BED_AND_BREAKFAST_DAYS,
    CAPITAL_GAIN_ALLOWANCES,
    INTERNAL_START_DATE,
)
from cgt_calc.dates import get_tax_year_end, get_tax_year_start
from cgt_calc.model import (
    CalculationEntry,
    CalculationLog,
    CapitalGainsReport,
    HmrcTransactionData,
    HmrcTransactionLog,
    PortfolioEntry,
    Position,
    RuleType,
)
from cgt_calc.transaction_log import add_to_list, has_key
from cgt_calc.util import round_decimal

if TYPE_CHECKING:
    from cgt_calc.current_price_fetcher import CurrentPriceFetcher
    from cgt_calc.hmrc_transactions import HmrcTransactions


LOGGER = logging.getLogger(__name__)


class CapitalGainsCalculator:
    """Main calculator class."""

    def __init__(
        self,
        tax_year: int,
        price_fetcher: CurrentPriceFetcher,
        calc_unrealized_gains: bool = False,
    ):
        """Create calculator object."""
        self.tax_year = tax_year

        self.tax_year_start_date = get_tax_year_start(tax_year)
        self.tax_year_end_date = get_tax_year_end(tax_year)

        self.price_fetcher = price_fetcher
        self.calc_unrealized_gains = calc_unrealized_gains

        self.bnb_list: HmrcTransactionLog = {}

        self.portfolio: dict[str, Position] = defaultdict(Position)

    def _process_acquisition(
        self,
        symbol: str,
        date_index: datetime.date,
        hmrc_transactions: HmrcTransactions,
    ) -> list[CalculationEntry]:
        """Process single acquisition."""
        acquisition = hmrc_transactions.acquisition_list[date_index][symbol]
        modified_amount = acquisition.amount
        position = self.portfolio[symbol]
        calculation_entries = []
        # Management fee transaction can have 0 quantity
        assert acquisition.quantity >= 0
        # Stock split can have 0 amount
        assert acquisition.amount >= 0

        bnb_acquisition = HmrcTransactionData()
        bed_and_breakfast_fees = Decimal(0)

        if acquisition.quantity > 0 and has_key(self.bnb_list, date_index, symbol):
            acquisition_price = acquisition.amount / acquisition.quantity
            bnb_acquisition = self.bnb_list[date_index][symbol]
            assert bnb_acquisition.quantity <= acquisition.quantity
            modified_amount -= bnb_acquisition.quantity * acquisition_price
            modified_amount += bnb_acquisition.amount
            assert modified_amount > 0
            bed_and_breakfast_fees = (
                acquisition.fees * bnb_acquisition.quantity / acquisition.quantity
            )
            calculation_entries.append(
                CalculationEntry(
                    rule_type=RuleType.BED_AND_BREAKFAST,
                    quantity=bnb_acquisition.quantity,
                    amount=-bnb_acquisition.amount,
                    new_quantity=position.quantity + bnb_acquisition.quantity,
                    new_pool_cost=position.amount + bnb_acquisition.amount,
                    fees=bed_and_breakfast_fees,
                    allowable_cost=acquisition.amount,
                )
            )
        self.portfolio[symbol] += Position(
            acquisition.quantity,
            modified_amount,
        )
        if (
            acquisition.quantity - bnb_acquisition.quantity > 0
            or bnb_acquisition.quantity == 0
        ):
            spin_off = next(
                (
                    spin_off
                    for spin_off in hmrc_transactions.spin_offs[date_index]
                    if spin_off.dest == symbol
                ),
                None,
            )
            calculation_entries.append(
                CalculationEntry(
                    rule_type=RuleType.SECTION_104,
                    quantity=acquisition.quantity - bnb_acquisition.quantity,
                    amount=-(modified_amount - bnb_acquisition.amount),
                    new_quantity=position.quantity + acquisition.quantity,
                    new_pool_cost=position.amount + modified_amount,
                    fees=acquisition.fees - bed_and_breakfast_fees,
                    allowable_cost=acquisition.amount,
                    spin_off=spin_off,
                )
            )
        return calculation_entries

    def _process_disposal(
        self,
        symbol: str,
        date_index: datetime.date,
        hmrc_transactions: HmrcTransactions,
    ) -> tuple[Decimal, list[CalculationEntry], CalculationEntry | None]:
        """Process single disposal."""
        disposal = hmrc_transactions.disposal_list[date_index][symbol]
        disposal_quantity = disposal.quantity
        proceeds_amount = disposal.amount
        original_disposal_quantity = disposal_quantity
        disposal_price = proceeds_amount / disposal_quantity
        current_quantity = self.portfolio[symbol].quantity
        spin_off_entry = None

        for date, spin_offs in hmrc_transactions.spin_offs.items():
            if date > date_index:
                continue
            for spin_off in spin_offs:
                # Up to the actual spin-off happening all the sales has to happen based
                # on original cost basis, after spin-off we have to consider its impact
                # for all future trades
                amount = self.portfolio[spin_off.source].amount
                quantity = self.portfolio[spin_off.source].quantity
                new_amount = amount * spin_off.cost_proportion
                LOGGER.debug(
                    "Detected spin-off of %s to %s on %s, modyfing the cost amount "
                    "from %d to %d according to cost-proportion: %.2f",
                    spin_off.source,
                    spin_off.dest,
                    spin_off.date,
                    amount,
                    new_amount,
                    spin_off.cost_proportion,
                )
                hmrc_transactions.spin_offs[date] = spin_offs[1:]
                self.portfolio[spin_off.source].amount = new_amount
                spin_off_entry = CalculationEntry(
                    RuleType.SPIN_OFF,
                    quantity=quantity,
                    amount=-amount,
                    new_quantity=quantity,
                    gain=None,
                    # Fees, if any are already accounted on the acquisition of
                    # spined off shares
                    fees=Decimal(0),
                    new_pool_cost=new_amount,
                    allowable_cost=new_amount,
                    spin_off=spin_off,
                )

        current_amount = self.portfolio[symbol].amount
        assert disposal_quantity <= current_quantity
        chargeable_gain = Decimal(0)
        calculation_entries = []
        # Same day rule is first
        if has_key(hmrc_transactions.acquisition_list, date_index, symbol):
            same_day_acquisition = hmrc_transactions.acquisition_list[date_index][
                symbol
            ]

            available_quantity = min(disposal_quantity, same_day_acquisition.quantity)
            if available_quantity > 0:
                acquisition_price = (
                    same_day_acquisition.amount / same_day_acquisition.quantity
                )
                same_day_proceeds = available_quantity * disposal_price
                same_day_allowable_cost = available_quantity * acquisition_price
                same_day_gain = same_day_proceeds - same_day_allowable_cost
                chargeable_gain += same_day_gain
                LOGGER.debug(
                    "SAME DAY, quantity %d, gain %s, disposal price %s, "
                    "acquisition price %s",
                    available_quantity,
                    same_day_gain,
                    disposal_price,
                    acquisition_price,
                )
                disposal_quantity -= available_quantity
                proceeds_amount -= available_quantity * disposal_price
                current_quantity -= available_quantity
                # These shares shouldn't be added to Section 104 holding
                current_amount -= available_quantity * acquisition_price
                if current_quantity == 0:
                    assert (
                        round_decimal(current_amount, 23) == 0
                    ), f"current amount {current_amount}"
                fees = disposal.fees * available_quantity / original_disposal_quantity
                calculation_entries.append(
                    CalculationEntry(
                        rule_type=RuleType.SAME_DAY,
                        quantity=available_quantity,
                        amount=same_day_proceeds,
                        gain=same_day_gain,
                        allowable_cost=same_day_allowable_cost,
                        fees=fees,
                        new_quantity=current_quantity,
                        new_pool_cost=current_amount,
                    )
                )

        # Bed and breakfast rule next
        if disposal_quantity > 0:
            for i in range(BED_AND_BREAKFAST_DAYS):
                search_index = date_index + datetime.timedelta(days=i + 1)
                if has_key(hmrc_transactions.acquisition_list, search_index, symbol):
                    acquisition = hmrc_transactions.acquisition_list[search_index][
                        symbol
                    ]

                    bnb_acquisition = (
                        self.bnb_list[search_index][symbol]
                        if has_key(self.bnb_list, search_index, symbol)
                        else HmrcTransactionData()
                    )
                    assert bnb_acquisition.quantity <= acquisition.quantity

                    same_day_disposal = (
                        hmrc_transactions.disposal_list[search_index][symbol]
                        if has_key(
                            hmrc_transactions.disposal_list, search_index, symbol
                        )
                        else HmrcTransactionData()
                    )
                    if same_day_disposal.quantity > acquisition.quantity:
                        # If the number of shares disposed of exceeds the number
                        # acquired on the same day the excess shares will be identified
                        # in the normal way.
                        continue

                    # This can be some management fee entry or already used
                    # by bed and breakfast rule
                    if (
                        acquisition.quantity
                        - same_day_disposal.quantity
                        - bnb_acquisition.quantity
                        == 0
                    ):
                        continue
                    print(
                        f"WARNING: Bed and breakfasting for {symbol}."
                        f" Disposed on {date_index}"
                        f" and acquired again on {search_index}"
                    )
                    available_quantity = min(
                        disposal_quantity,
                        acquisition.quantity
                        - same_day_disposal.quantity
                        - bnb_acquisition.quantity,
                    )
                    acquisition_price = acquisition.amount / acquisition.quantity
                    bed_and_breakfast_proceeds = available_quantity * disposal_price
                    bed_and_breakfast_allowable_cost = (
                        available_quantity * acquisition_price
                    )
                    bed_and_breakfast_gain = (
                        bed_and_breakfast_proceeds - bed_and_breakfast_allowable_cost
                    )
                    chargeable_gain += bed_and_breakfast_gain
                    LOGGER.debug(
                        "BED & BREAKFAST, quantity %d, gain %s, disposal price %s, "
                        "acquisition price %s",
                        available_quantity,
                        bed_and_breakfast_gain,
                        disposal_price,
                        acquisition_price,
                    )
                    disposal_quantity -= available_quantity
                    proceeds_amount -= available_quantity * disposal_price
                    current_price = current_amount / current_quantity
                    amount_delta = available_quantity * current_price
                    current_quantity -= available_quantity
                    current_amount -= amount_delta
                    if current_quantity == 0:
                        assert (
                            round_decimal(current_amount, 23) == 0
                        ), f"current amount {current_amount}"
                    add_to_list(
                        self.bnb_list,
                        search_index,
                        symbol,
                        available_quantity,
                        amount_delta,
                        Decimal(0),
                    )
                    fees = (
                        disposal.fees * available_quantity / original_disposal_quantity
                    )
                    calculation_entries.append(
                        CalculationEntry(
                            rule_type=RuleType.BED_AND_BREAKFAST,
                            quantity=available_quantity,
                            amount=bed_and_breakfast_proceeds,
                            gain=bed_and_breakfast_gain,
                            allowable_cost=bed_and_breakfast_allowable_cost,
                            fees=fees,
                            bed_and_breakfast_date_index=search_index,
                            new_quantity=current_quantity,
                            new_pool_cost=current_amount,
                        )
                    )
        if disposal_quantity > 0:
            allowable_cost = current_amount * disposal_quantity / current_quantity
            chargeable_gain += proceeds_amount - allowable_cost
            LOGGER.debug(
                "SECTION 104, quantity %d, gain %s, proceeds amount %s, "
                "allowable cost %s",
                disposal_quantity,
                proceeds_amount - allowable_cost,
                proceeds_amount,
                allowable_cost,
            )
            current_quantity -= disposal_quantity
            current_amount -= allowable_cost
            if current_quantity == 0:
                assert (
                    round_decimal(current_amount, 10) == 0
                ), f"current amount {current_amount}"
            fees = disposal.fees * disposal_quantity / original_disposal_quantity
            calculation_entries.append(
                CalculationEntry(
                    rule_type=RuleType.SECTION_104,
                    quantity=disposal_quantity,
                    amount=proceeds_amount,
                    gain=proceeds_amount - allowable_cost,
                    allowable_cost=allowable_cost,
                    fees=fees,
                    new_quantity=current_quantity,
                    new_pool_cost=current_amount,
                )
            )
            disposal_quantity = Decimal(0)

        assert (
            round_decimal(disposal_quantity, 23) == 0
        ), f"disposal quantity {disposal_quantity}"
        self.portfolio[symbol] = Position(current_quantity, current_amount)
        chargeable_gain = round_decimal(chargeable_gain, 2)
        return chargeable_gain, calculation_entries, spin_off_entry

    def calculate_capital_gain(
        self,
        hmrc_transactions: HmrcTransactions,
    ) -> CapitalGainsReport:
        """Calculate capital gain and return generated report."""
        begin_index = INTERNAL_START_DATE
        disposal_count = 0
        disposal_proceeds = Decimal(0)
        allowable_costs = Decimal(0)
        capital_gain = Decimal(0)
        capital_loss = Decimal(0)
        calculation_log: CalculationLog = defaultdict(dict)
        self.portfolio.clear()

        for date_index in (
            begin_index + datetime.timedelta(days=x)
            for x in range((self.tax_year_end_date - begin_index).days + 1)
        ):
            if date_index in hmrc_transactions.acquisition_list:
                for symbol in hmrc_transactions.acquisition_list[date_index]:
                    calculation_entries = self._process_acquisition(
                        symbol,
                        date_index,
                        hmrc_transactions,
                    )
                    if date_index >= self.tax_year_start_date:
                        calculation_log[date_index][f"buy${symbol}"] = (
                            calculation_entries
                        )
            if date_index in hmrc_transactions.disposal_list:
                for symbol in hmrc_transactions.disposal_list[date_index]:
                    (
                        transaction_capital_gain,
                        calculation_entries,
                        spin_off_entry,
                    ) = self._process_disposal(
                        symbol,
                        date_index,
                        hmrc_transactions,
                    )
                    if date_index >= self.tax_year_start_date:
                        disposal_count += 1
                        transaction_disposal_proceeds = hmrc_transactions.disposal_list[
                            date_index
                        ][symbol].amount
                        disposal_proceeds += transaction_disposal_proceeds
                        allowable_costs += (
                            transaction_disposal_proceeds - transaction_capital_gain
                        )
                        transaction_quantity = hmrc_transactions.disposal_list[
                            date_index
                        ][symbol].quantity
                        LOGGER.debug(
                            "DISPOSAL on %s of %s, quantity %d, capital gain $%s",
                            date_index,
                            symbol,
                            transaction_quantity,
                            round_decimal(transaction_capital_gain, 2),
                        )
                        calculated_quantity = Decimal(0)
                        calculated_proceeds = Decimal(0)
                        calculated_gain = Decimal(0)
                        for entry in calculation_entries:
                            calculated_quantity += entry.quantity
                            calculated_proceeds += entry.amount
                            calculated_gain += entry.gain
                        assert transaction_quantity == calculated_quantity
                        assert round_decimal(
                            transaction_disposal_proceeds, 10
                        ) == round_decimal(
                            calculated_proceeds, 10
                        ), f"{transaction_disposal_proceeds} != {calculated_proceeds}"
                        assert transaction_capital_gain == round_decimal(
                            calculated_gain, 2
                        )
                        calculation_log[date_index][f"sell${symbol}"] = (
                            calculation_entries
                        )
                        if transaction_capital_gain > 0:
                            capital_gain += transaction_capital_gain
                        else:
                            capital_loss += transaction_capital_gain
                        if spin_off_entry is not None:
                            spin_off = spin_off_entry.spin_off
                            assert spin_off is not None
                            calculation_log[spin_off.date][
                                f"spin-off${spin_off.source}"
                            ] = [spin_off_entry]
        print("\nSecond pass completed")
        allowance = CAPITAL_GAIN_ALLOWANCES.get(self.tax_year)

        return CapitalGainsReport(
            self.tax_year,
            [
                self._make_portfolio_entry(symbol, position.quantity, position.amount)
                for symbol, position in self.portfolio.items()
            ],
            disposal_count,
            round_decimal(disposal_proceeds, 2),
            round_decimal(allowable_costs, 2),
            round_decimal(capital_gain, 2),
            round_decimal(capital_loss, 2),
            Decimal(allowance) if allowance is not None else None,
            calculation_log,
            show_unrealized_gains=self.calc_unrealized_gains,
        )

    def _make_portfolio_entry(
        self, symbol: str, quantity: Decimal, amount: Decimal
    ) -> PortfolioEntry:
        """Create a portfolio entry in the report."""
        # (by calculating the unrealized gains)
        unrealized_gains = None
        if self.calc_unrealized_gains:
            current_price = (
                self.price_fetcher.get_current_market_price(symbol)
                if quantity > 0
                else 0
            )
            if current_price is not None:
                unrealized_gains = current_price * quantity - amount
        return PortfolioEntry(
            symbol,
            quantity,
            amount,
            unrealized_gains,
        )
