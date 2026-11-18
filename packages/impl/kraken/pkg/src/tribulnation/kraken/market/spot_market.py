"""One Kraken Spot market."""

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import uuid

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Fees,
  Order,
  OrderResponse,
  OrderState,
  Settings,
  SpotBalances,
  SpotMarket as BaseSpotMarket,
  SpotRules,
  Trade,
)

from .impl import (
  MarketMixin,
  balances,
  depth,
  depth_stream,
  rules,
  trades_history,
  trades_stream,
)
from .impl import orders
from .impl.candles import CANDLE_INTERVALS, candles


@dataclass(frozen=True, kw_only=True)
class SpotMarket(MarketMixin, BaseSpotMarket):
  """Kraken implementation of `SpotMarket`, for one Spot pair (`kraken:spot:KAVAUSD`).

  Orders are REST limit orders on the Spot API key; balances are `BalanceEx`, shared
  per `ttl` across the account's markets.

  Settings, under `settings['kraken']` (the perpetuals' `KrakenSettings`):
  `{'time_in_force': 'ioc'}` sends a `LIMIT` as immediate-or-cancel (`'post'`:
  post-only). `reduce_only` raises `ValueError`: Spot has no position to reduce.
  """

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def market_id(self) -> str:
    return self.altname

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    return await depth(self, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    return depth_stream(self, levels=levels, queue_size=queue_size, overflow=overflow)

  async def rules(self, *, refetch: bool = False) -> SpotRules:
    """The pair's `AssetPairs` rules, with its internal base and quote asset ids."""
    return await rules(self, refetch=refetch)

  async def balances(self, *, ttl: timedelta | None = None) -> SpotBalances:
    """Base and quote balances from `BalanceEx`; `free` excludes `hold_trade`."""
    return await balances(self, ttl=ttl)

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Fetch the current account's per-pair schedule, converting percent to fractions.

    Kraken returns one shared rate for pairs without a maker/taker distinction.
    A missing maker entry on a pair with a split public schedule is not a flat fee.
    """
    response = await self.call_kraken(
      lambda: self.client.spot.account.trade_volume(self.altname)
    )
    key = self.meta['pair']['key']
    taker_rows = response.get('fees') or {}
    maker_rows = response.get('fees_maker') or {}
    taker = taker_rows.get(key)
    maker = maker_rows.get(key)
    if taker is None:
      raise ValueError('Kraken account fees omitted the requested pair')
    if maker is None:
      if self.info.get('fees_maker'):
        raise ValueError('Kraken account fees omitted the maker rate')
      maker_rate = taker['fee']
    else:
      maker_rate = maker['fee']
    return Fees.symmetric(
      maker=Decimal(maker_rate) / 100,
      taker=Decimal(taker['fee']) / 100,
    )

  def candles(
    self,
    interval: CandleInterval,
    start: datetime,
    end: datetime,
  ) -> PaginatedResponse[Candle]:
    """Fetch the retained trade candles whose opens fall within the requested range."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(candles(self, interval, start, end))

  CANDLE_INTERVALS = CANDLE_INTERVALS

  async def open_orders(self) -> Sequence[OrderState]:
    return await orders.open_orders(self)

  async def query_order(self, id: str) -> OrderState | None:
    """One order by txid, open or closed (`QueryOrders`); `None` when unknown."""
    return await orders.query_order(self, id)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    return PaginatedResponse(trades_history(self, start, end))

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    return trades_stream(self, queue_size=queue_size, overflow=overflow)

  def random_client_order_id(self) -> str:
    """A fresh UUID, one of the forms Kraken's `cl_ord_id` takes."""
    return str(uuid.uuid4())

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place a `LIMIT` (GTC), `POST_ONLY` (`post` flag) or `MARKET` (IOC limit at
    `price`); fees in the quote asset. `filled_qty` is `None`: `AddOrder` reports no
    execution.

    Raises:
      OrderRejected: Kraken refused it: insufficient funds, below the minimums, a
        post-only that would cross, an invalid price or size, ...
    """
    return await orders.place_order(self, order, settings=settings)

  async def replace_order(
    self, id: str, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Amend `id` in place (`AmendOrder`, same txid); see `orders.replace_order`."""
    return await orders.replace_order(self, id, order, settings=settings)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel one order; `OrderNotFound` when Kraken no longer knows it."""
    return await orders.cancel_order(self, id)
