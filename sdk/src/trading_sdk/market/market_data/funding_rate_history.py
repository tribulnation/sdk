from typing_extensions import Protocol, AsyncIterable, Sequence, Literal
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

@dataclass
class Funding:
  rate: Decimal
  time: datetime

class FundingRateHistory(Protocol):
  def funding_rate_history(
    self, base: str, quote: str, /, *,
    start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    """Fetch funding rate history for a given perpetual instrument.

    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: if given, retrieves funding rates after this time.
    - `end`: if given, retrieves funding rates before this time.
    """
    ...

class InversePerpFundingRateHistory(Protocol):
  async def inverse_perp_funding_rate_history(
    self, currency: str, /, *,
    start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    """Fetch funding rate history for a given inverse perpetual instrument.

    - `currency`: The currency, e.g. `BTC`.
    - `start`: if given, retrieves funding rates after this time.
    - `end`: if given, retrieves funding rates before this time.
    """
    ...