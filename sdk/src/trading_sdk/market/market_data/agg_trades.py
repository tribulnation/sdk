from typing_extensions import Protocol, Literal, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_sdk.market.types import Instrument

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
  async def trades(
    self, instrument: Instrument, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[AggTrade]]:
    """Fetch aggregate trades for the given symbol. Automatically paginates if needed.
    
    - `instrument`: The instrument to get the aggregate trades for.
    - `start`: if given, retrieves trades after this time.
    - `end`: if given, retrieves trades before this time.
    """
    ...

  async def trades_any(self, instrument: str, *, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Sequence[AggTrade]]:
    """Fetch aggregate trades for the given instrument by the exchange-specific name.
    
    - `instrument`: The name of the instrument to get the aggregate trades for.
    - `start`: if given, retrieves trades after this time.
    - `end`: if given, retrieves trades before this time.
    """
    async for trades in self.trades({'type': 'any', 'name': instrument}, start=start, end=end):
      yield trades

  async def trades_spot(self, base: str, quote: str, *, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Sequence[AggTrade]]:
    """Fetch aggregate trades for the given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: if given, retrieves trades after this time.
    - `end`: if given, retrieves trades before this time.
    """
    async for trades in self.trades({'type': 'spot', 'base': base, 'quote': quote}, start=start, end=end):
      yield trades

  async def trades_perp(self, base: str, quote: str, *, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Sequence[AggTrade]]:
    """Fetch aggregate trades for the given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: if given, retrieves trades after this time.
    - `end`: if given, retrieves trades before this time.
    """
    async for trades in self.trades({'type': 'perp', 'base': base, 'quote': quote}, start=start, end=end):
      yield trades
