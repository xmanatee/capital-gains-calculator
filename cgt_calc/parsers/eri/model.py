"""Model classes for ERI."""

import datetime
from decimal import Decimal

from cgt_calc.model import ActionType, BrokerSource, BrokerTransaction


class EriTransaction(BrokerTransaction):
    """Eri transaction data."""

    def __init__(
        self,
        date: datetime.date,
        symbol: str,
        isin: str,
        price: Decimal,
        currency: str,
    ) -> None:
        """Create an Eri transaction."""
        super().__init__(
            date=date,
            action=ActionType.EXCESS_REPORTED_INCOME,
            symbol=symbol,
            description=f"Excess Reported Income for {isin}",
            quantity=None,
            price=price,
            fees=Decimal(0),
            amount=None,
            currency=currency,
            broker_source=BrokerSource.ERI,
        )
        self.metadata["isin"] = isin
