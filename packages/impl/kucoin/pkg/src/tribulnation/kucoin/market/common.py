"""Shared public metadata, client ownership and native market identities."""

import asyncio
from dataclasses import dataclass, field
from typing_extensions import AsyncContextManager, Iterable, Literal

from typed_kucoin.schemas import FuturesContract, SpotSymbol
from tribulnation.sdk import SDK
from tribulnation.sdk.core import Subscription
from tribulnation.sdk.market import Book
from ..core import Mixin


def linear_perpetual(row: FuturesContract) -> bool:
  """Select perpetuals whose positive multiplier converts lots to base units."""
  return (
    row['expireDate'] is None
    and not row['isInverse']
    and row['settleCurrency'] == row['quoteCurrency']
    and row['multiplier'] > 0
  )


@dataclass(frozen=True, kw_only=True)
class Shared(Mixin):
  """Own one client and cache instrument definitions and shared book feeds."""

  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  spot: dict[str, SpotSymbol] = field(default_factory=dict[str, SpotSymbol])
  perp: dict[str, FuturesContract] = field(default_factory=dict[str, FuturesContract])
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[tuple[str, str], Subscription[Book]] = field(
    default_factory=dict[tuple[str, str], Subscription[Book]]
  )

  async def spot_symbols(self, *, refetch: bool = False) -> dict[str, SpotSymbol]:
    """Cache the venue's complete spot definitions, including disabled pairs."""
    async with self.lock:
      if refetch or not self.spot:
        rows = await self.call(self.client.spot.all_symbols)
        self.spot.clear()
        self.spot.update((row['symbol'], row) for row in rows)
    return self.spot

  async def perp_symbols(self, *, refetch: bool = False) -> dict[str, FuturesContract]:
    """Cache active linear perpetuals, excluding inverse and dated contracts."""
    async with self.lock:
      if refetch or not self.perp:
        rows = await self.call(self.client.futures.all_symbols)
        self.perp.clear()
        self.perp.update(
          (row['symbol'], row)
          for row in rows
          if linear_perpetual(row) and row['status'] == 'Open'
        )
    return self.perp


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange and market objects."""

  shared: Shared

  @property
  def venue_id(self) -> Literal['kucoin']:
    """The Catalogue platform ID."""
    return 'kucoin'

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared
