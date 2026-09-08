"""Bitget's spot market."""

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Collateral,
  Market,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Settings,
  Trade,
)

from .impl import (
  MarketMixin,
  Product,
  depth_stream,
  open_orders,
  parse_book,
  parse_spot_rules,
  spot_collateral,
  spot_position,
  trades_history,
  trades_stream,
)


@dataclass(kw_only=True, frozen=True)
class SpotMarket(MarketMixin, Market):
  """One Bitget spot pair, e.g. `BTCUSDT`."""

  @property
  def product(self) -> Product:
    return 'SPOT'

  @property
  def market_id(self) -> str:
    return self.symbol

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def venue_id(self) -> str:
    return 'bitget'

  async def depth(self, *, levels: int | None = None) -> Book:
    """Fetch the market order book (150 levels a side when `levels` is omitted)."""
    book = await self.call(
      lambda: self.client.classic.spot.orderbook(
        self.symbol, limit=levels, validate=self.validate
      )
    )
    return parse_book(book['bids'], book['asks'])

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the market order book."""
    return depth_stream(self, levels=levels, queue_size=queue_size, overflow=overflow)

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Fetch the market rules from the public symbol catalogue.

    Args:
      refetch: Refetch the catalogue instead of reading the cached one.
    """
    symbols = await self.spot_symbols(refetch=refetch)
    return parse_spot_rules(symbols[self.symbol])

  async def open_orders(self) -> Sequence[OrderState]:
    """Fetch your currently open orders."""
    return await open_orders(self)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Fetch your trades history."""
    return PaginatedResponse(trades_history(self, start, end))

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades."""
    return trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def position(self) -> Position:
    """Fetch your base-asset balance in the market."""
    symbols = await self.spot_symbols()
    return await spot_position(self, symbols[self.symbol]['baseCoin'])

  async def collateral(self) -> Collateral:
    """Fetch the quote-asset balance backing this market."""
    symbols = await self.spot_symbols()
    return await spot_collateral(self, symbols[self.symbol]['quoteCoin'])

  async def available_notional(self) -> Decimal:
    """Fetch the free quote-asset balance."""
    return (await self.collateral()).free_collateral

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Not implemented: Bitget is not a venue we trade on."""
    raise NotImplementedError('Trading is not implemented for Bitget.')

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Not implemented: Bitget is not a venue we trade on."""
    raise NotImplementedError('Trading is not implemented for Bitget.')
