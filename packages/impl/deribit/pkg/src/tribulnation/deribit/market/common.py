"""Shared public instrument discovery and managed Deribit ownership."""

import asyncio
from dataclasses import dataclass, field
from typing_extensions import AsyncContextManager, Iterable, Literal
from typed_deribit.market_data.get_instruments import InstrumentItem
from typed_deribit.market_data.ticker import Ticker
from tribulnation.sdk import SDK
from tribulnation.sdk.core import Subscription
from tribulnation.sdk.market import Book
from ..core import Mixin

Product = Literal['spot', 'perp']


def product(row: InstrumentItem) -> Product | None:
  """Select active spot and linear perpetuals with equal quote and settlement units."""
  if not row['is_active']:
    return None
  if row['kind'] == 'spot':
    return 'spot'
  if (
    row['kind'] == 'future'
    and row.get('settlement_period') == 'perpetual'
    and row.get('instrument_type') == 'linear'
    and row.get('settlement_currency') == row['quote_currency']
  ):
    return 'perp'
  return None


@dataclass(frozen=True, kw_only=True)
class Shared(Mixin):
  """Own one credential-free client and cache its supported native definitions."""

  inventory: dict[Literal['instruments'], dict[str, InstrumentItem]] = field(
    default_factory=dict[Literal['instruments'], dict[str, InstrumentItem]]
  )
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  ticker_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )

  async def symbols(self, *, refetch: bool = False) -> dict[str, InstrumentItem]:
    """Fetch discovery once, including a genuinely empty inventory."""
    async with self.lock:
      if refetch or 'instruments' not in self.inventory:
        rows = await self.call(
          lambda: self.client.market_data.get_instruments(currency='any', expired=False)
        )
        selected = {r['instrument_name']: r for r in rows if product(r) is not None}
        self.inventory['instruments'] = selected
    return self.inventory['instruments']

  async def ticker(self, symbol: str) -> Ticker:
    """Pace shared ticker reads to at most ten requests per second."""
    async with self.ticker_lock:
      await asyncio.sleep(0.1)
      return await self.call(lambda: self.client.market_data.ticker(symbol))


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Borrow the same resource owner across venue, exchanges and markets."""

  shared: Shared

  @property
  def venue_id(self) -> str:
    """The mainnet Catalogue platform identity."""
    return 'deribit'

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared managed client owner."""
    yield self.shared
