from typing_extensions import Protocol, Literal, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass
class AggTrade:
  price: Decimal
  qty: Decimal
  """Base asset quantity."""
  time: datetime
  """Time of the transaction."""
  maker: Literal['buyer', 'seller']
  """Which side was the maker."""

  
class AggTrades(Protocol):
  async def agg_trades(
    self, instrument: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[AggTrade]]:
    """Fetch aggregate trades for the given symbol. Automatically paginates if needed.
    
    - `instrument`: The instrument to get the aggregate trades for.
    - `start`: if given, retrieves trades after this time.
    - `end`: if given, retrieves trades before this time.
    """
    ...

class SpotAggTrades(AggTrades, Protocol):
  async def spot_agg_trades(
    self, base: str, quote: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[AggTrade]]:
    """Fetch aggregate trades for the given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: if given, retrieves trades after this time.
    - `end`: if given, retrieves trades before this time.
    """
    ...

class PerpAggTrades(AggTrades, Protocol):
  async def perp_agg_trades(
    self, base: str, quote: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[AggTrade]]:
    """Fetch aggregate trades for the given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: if given, retrieves trades after this time.
    - `end`: if given, retrieves trades before this time.
    """
    ...

class InversePerpAggTrades(AggTrades, Protocol):
  async def inverse_perp_agg_trades(
    self, currency: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[AggTrade]]:
    """Fetch aggregate trades for the given inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `start`: if given, retrieves trades after this time.
    - `end`: if given, retrieves trades before this time.
    """
    ...