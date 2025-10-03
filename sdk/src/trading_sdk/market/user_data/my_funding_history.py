from typing_extensions import Protocol, AsyncIterable, Sequence, Literal
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

@dataclass
class Funding:
  funding: Decimal
  time: datetime
  side: Literal['LONG', 'SHORT']
  currency: str
  rate: Decimal | None = None

class MyFundingHistory(Protocol):
  def my_funding_history(
    self, instrument: str, /, *,
    start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    """Fetch funding rate history for a given perpetual instrument.

    - `instrument`: The instrument, e.g. `BTCUSDT`.
    - `start`: if given, retrieves funding rates after this time.
    - `end`: if given, retrieves funding rates before this time.
    """
    ...

class PerpMyFundingHistory(MyFundingHistory, Protocol):
  def perp_my_funding_history(
    self, base: str, quote: str, /, *,
    start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    """Fetch funding rate history for a given linear perpetual instrument.

    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: if given, retrieves funding rates after this time.
    - `end`: if given, retrieves funding rates before this time.
    """
    ...

class InversePerpMyFundingHistory(MyFundingHistory, Protocol):
  def inverse_perp_my_funding_history(
    self, currency: str, /, *,
    start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    """Fetch funding rate history for a given inverse perpetual instrument.

    - `currency`: The currency, e.g. `BTC`.
    - `start`: if given, retrieves funding rates after this time.
    - `end`: if given, retrieves funding rates before this time.
    """
    ...