"""Model classes."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from .util import round_decimal


@dataclass
class SpinOff:
    """Class representing spin-off event on a share."""

    # Cost proportion to be applied to the cost of original shares from which
    # Spin-off originated
    cost_proportion: Decimal
    # Source of the Spin-off, e.g MMM for SOLV
    source: str
    # Dest ticker to which SpinOff happened, e.g. SOLV for MMM
    dest: str
    # When the spin-off happened
    date: datetime.date


@dataclass
class HmrcTransactionData:
    """Hmrc transaction figures."""

    quantity: Decimal = Decimal(0)
    amount: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)

    def __add__(self, transaction: HmrcTransactionData) -> HmrcTransactionData:
        """Add two transactions."""
        return self.__class__(
            self.quantity + transaction.quantity,
            self.amount + transaction.amount,
            self.fees + transaction.fees,
        )


# For mapping of dates to int
HmrcTransactionLog = dict[datetime.date, dict[str, HmrcTransactionData]]


class Broker(Enum):
    UNKNOWN = "Unknown Broker"
    SCHWAB = "Schwab"
    MSSB = "Morgan Stanley"
    SHARESIGHT = "Sharesight"
    TRADING_212 = "Trading 212"

    def __init__(self, readable_name: str):
        self.readable_name = readable_name


class BrokerSource(Enum):
    UNKNOWN = ("Unknown Source", Broker.UNKNOWN)
    SCHWAB_INDIVIDUAL = ("Schwab Individual", Broker.SCHWAB)
    SCHWAB_AWARDS = ("Schwab Awards", Broker.SCHWAB)
    MSSB_RELEASE = ("Morgan Stanley Release", Broker.MSSB)
    MSSB_WITHDRAWAL = ("Morgan Stanley Withdrawal", Broker.MSSB)
    SHARESIGHT = ("Sharesight", Broker.SHARESIGHT)
    TRADING_212 = ("Trading 212", Broker.TRADING_212)

    def __init__(self, readable_name: str, broker: Broker):
        self.readable_name = readable_name
        self.broker = broker


class ActionType(Enum):
    """Type of transaction action."""

    UNKNOWN = 0
    BUY = 1
    SELL = 2
    TRANSFER = 3
    STOCK_ACTIVITY = 4
    DIVIDEND = 5
    TAX = 6
    FEE = 7
    ADJUSTMENT = 8
    CAPITAL_GAIN = 9
    SPIN_OFF = 10
    INTEREST = 11
    REINVEST_SHARES = 12
    REINVEST_DIVIDENDS = 13
    WIRE_FUNDS_RECEIVED = 14
    STOCK_SPLIT = 15
    CASH_MERGER = 16


@dataclass
class BrokerTransaction:
    """Broken transaction data."""

    date: datetime.date
    action: ActionType
    symbol: str | None
    description: str
    quantity: Decimal | None
    price: Decimal | None
    fees: Decimal
    amount: Decimal | None
    currency: str
    broker_source: BrokerSource


class RuleType(Enum):
    """HMRC rule type."""

    SECTION_104 = 1
    SAME_DAY = 2
    BED_AND_BREAKFAST = 3
    SPIN_OFF = 4


@dataclass
class CalculationEntry:
    rule_type: RuleType
    quantity: Decimal
    amount: Decimal
    fees: Decimal
    new_quantity: Decimal
    new_pool_cost: Decimal
    gain: Decimal = Decimal(0)
    allowable_cost: Decimal = Decimal(0)
    bed_and_breakfast_date_index: Optional[datetime.date] = None
    spin_off: Optional[SpinOff] = None

    def __post_init__(self) -> None:
        if self.amount >= 0 and self.rule_type is not RuleType.SPIN_OFF:
            # Ensure gain is amount - allowable_cost if not explicitly set
            # If gain is already set, assert it's consistent:
            expected_gain = self.amount - self.allowable_cost
            assert (
                self.gain == expected_gain
            ), f"gain ({self.gain}) != amount - allowable_cost ({expected_gain})"


CalculationLog = dict[datetime.date, dict[str, list[CalculationEntry]]]


@dataclass
class Position:
    """A single position in the portfolio."""

    quantity: Decimal = Decimal(0)
    amount: Decimal = Decimal(0)

    def __add__(self, other: Position) -> Position:
        """Add two positions."""
        return Position(
            self.quantity + other.quantity,
            self.amount + other.amount,
        )

    def __sub__(self, other: Position) -> Position:
        """Subtract two positions."""
        return Position(
            self.quantity - other.quantity,
            self.amount - other.amount,
        )

    def __str__(self) -> str:
        """Return string representation."""
        return str(round_decimal(self.quantity, 2))


class PortfolioEntry:
    """A single symbol entry for the portfolio in the final report."""

    def __init__(
        self,
        symbol: str,
        quantity: Decimal,
        amount: Decimal,
        unrealized_gains: Decimal | None,
    ):
        """Create portfolio entry."""
        self.symbol = symbol
        self.quantity = quantity
        self.amount = amount
        self.unrealized_gains = unrealized_gains

    def unrealized_gains_str(self) -> str:
        """Format the unrealized gains to show in the report."""
        if self.unrealized_gains is None:
            str_val = "unknown"
        else:
            str_val = f"£{round_decimal(self.unrealized_gains, 2)}"

        return f" (unrealized gains: {str_val})"

    def __repr__(self) -> str:
        """Return print representation."""
        return f"<PortfolioEntry {self!s}>"

    def __str__(self) -> str:
        """Return string representation."""
        return (
            f"  {self.symbol}: {round_decimal(self.quantity, 2)}, "
            f"£{round_decimal(self.amount, 2)}"
        )


@dataclass
class CapitalGainsReport:
    """Store calculated report."""

    tax_year: int
    portfolio: list[PortfolioEntry]
    disposal_count: int
    disposal_proceeds: Decimal
    allowable_costs: Decimal
    capital_gain: Decimal
    capital_loss: Decimal
    capital_gain_allowance: Decimal | None
    calculation_log: CalculationLog
    show_unrealized_gains: bool

    def total_unrealized_gains(self) -> Decimal:
        """Total unrealized gains across portfolio."""
        return sum(
            (
                h.unrealized_gains
                for h in self.portfolio
                if h.unrealized_gains is not None
            ),
            Decimal(0),
        )

    def total_gain(self) -> Decimal:
        """Total capital gain."""
        return self.capital_gain + self.capital_loss

    def taxable_gain(self) -> Decimal:
        """Taxable gain with current allowance."""
        assert self.capital_gain_allowance is not None
        return max(Decimal(0), self.total_gain() - self.capital_gain_allowance)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"<CalculationEntry: {self!s}>"

    def __str__(self) -> str:
        """Return string representation."""
        out = f"Portfolio at the end of {self.tax_year}/{self.tax_year + 1} tax year:\n"
        for entry in self.portfolio:
            if entry.quantity > 0:
                unrealized_gains_str = (
                    entry.unrealized_gains_str() if self.show_unrealized_gains else ""
                )
                out += f"{entry!s}{unrealized_gains_str}\n"
        out += f"For tax year {self.tax_year}/{self.tax_year + 1}:\n"
        out += f"Number of disposals: {self.disposal_count}\n"
        out += f"Disposal proceeds: £{self.disposal_proceeds}\n"
        out += f"Allowable costs: £{self.allowable_costs}\n"
        out += f"Capital gain: £{self.capital_gain}\n"
        out += f"Capital loss: £{-self.capital_loss}\n"
        out += f"Total capital gain: £{self.total_gain()}\n"
        if self.capital_gain_allowance is not None:
            out += f"Taxable capital gain: £{self.taxable_gain()}\n"
        else:
            out += "WARNING: Missing allowance for this tax year\n"
        if self.show_unrealized_gains:
            total_unrealized_gains = round_decimal(self.total_unrealized_gains(), 2)
            out += f"Total unrealized gains: £{total_unrealized_gains}\n"
            if any(h.unrealized_gains is None for h in self.portfolio):
                out += (
                    "WARNING: Some unrealized gains couldn't be calculated."
                    " Take a look at the symbols with unknown unrealized gains above"
                    " and factor in their prices.\n"
                )
        return out
