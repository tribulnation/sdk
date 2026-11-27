"""Market methods whose shape is the same on KuCoin spot and linear perpetuals."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  Awaitable,
  Iterator,
  Sequence,
)

from typed_kucoin import KuCoin
from tribulnation.sdk.core import (
  Error,
  OrderNotFound,
  OrderRejected,
  OverflowPolicy,
  PositionLimitExceeded,
)
from tribulnation.sdk.market import (
  Book,
  Market,
  Order,
  OrderResponse,
  OrderState,
  Settings,
  Trade,
)
from ..errors import POSITION_LIMIT_CODES, error_code, not_found, refused
from . import books
from .candles import CANDLE_INTERVALS
from .common import OrderEvent, Public, Scope
from .fills import connect_orders
from .orders import NativeOrder, native_order, random_client_oid

TRADES_WINDOW = timedelta(days=7)
"""The widest `startAt`/`endAt` span either fills endpoint accepts."""
BATCH = 20
"""Most orders one batch placement takes, on either product line."""


def windows(
  start: datetime, end: datetime, now: datetime
) -> Iterator[tuple[datetime, datetime]]:
  """Inclusive millisecond windows of at most `TRADES_WINDOW` covering `[start, min(end, now)]`."""
  horizon = min(end, now)
  lower = start
  while lower <= horizon:
    upper = min(lower + TRADES_WINDOW - timedelta(milliseconds=1), horizon)
    yield lower, upper
    lower = upper + timedelta(milliseconds=1)


def refusal(exc: Error) -> OrderRejected:
  """The `OrderRejected` for a definitive refusal; `PositionLimitExceeded` for its codes."""
  if error_code(exc) in POSITION_LIMIT_CODES:
    return PositionLimitExceeded(*exc.args)
  else:
    return OrderRejected(*exc.args)


@dataclass(frozen=True, kw_only=True)
class NativeMarket(Public, Market):
  """One native symbol of either product line."""

  symbol: str
  CANDLE_INTERVALS = CANDLE_INTERVALS

  @property
  @abstractmethod
  def scope(self) -> Scope:
    """The product line this symbol trades on."""

  @property
  @abstractmethod
  def multiplier(self) -> Decimal:
    """Base units per native quantity unit: `1` on spot, the contract size on perpetuals."""

  @property
  def client(self) -> KuCoin:
    """The shared typed client."""
    return self.shared.client

  @property
  def market_id(self) -> str:
    """Keep the native KuCoin symbol."""
    return self.symbol

  @property
  def exchange_id(self) -> str:
    """`spot` or `perp`, the Catalogue's explicit exchange IDs."""
    return self.scope

  @abstractmethod
  def submit(self, order: NativeOrder) -> Awaitable[OrderResponse]:
    """Send one validated order, raising venue errors untranslated by `place_order`."""

  @abstractmethod
  def cancel(self, id: str) -> Awaitable[object]:
    """Cancel one native order by its KuCoin order ID."""

  @abstractmethod
  def fetch_order(self, id: str) -> Awaitable[OrderState | None]:
    """Read one native order of this symbol, `None` when it belongs to another."""

  @abstractmethod
  def event_trade(self, event: OrderEvent) -> Trade | None:
    """The fill an order push of this symbol reports, if any."""

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """Fetch up to 100 public price levels per side, in base units."""
    return await books.depth(
      self.shared, self.exchange_id, self.symbol, self.multiplier, levels=levels
    )

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to up to five levels with bounded per-subscriber buffering."""
    return books.depth_stream(
      self.shared,
      self.exchange_id,
      self.symbol,
      self.multiplier,
      levels=levels,
      queue_size=queue_size,
      overflow=overflow,
    )

  def random_client_order_id(self) -> str:
    """128 random bits as 32 hex digits, within KuCoin's 40-character `clientOid`."""
    return random_client_oid()

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place a `LIMIT` (GTC), `POST_ONLY` (`postOnly`) or `MARKET` (IOC limit at the price) order.

    The order is validated against `rules()` first; nothing is rounded. Without a
    `client_order_id`, a random one is sent.

    Raises:
      ValueError: The order is off the tick or step grid, below the minimum size or
        notional, above the maximum, or (perpetuals) not a whole number of contracts.
      OrderRejected: KuCoin refused it with a definitive code, or answered that it ended
        with nothing filled (a crossing post-only or an unmatched IOC, where KuCoin
        reports the outcome at placement).
      PositionLimitExceeded: The refusal says the position limit is reached.
    """
    native = native_order(order, await self.rules())
    try:
      return await self.submit(native)
    except Error as exc:
      if refused(exc):
        raise refusal(exc) from exc
      raise

  async def place_orders(
    self, orders: Sequence[Order], *, settings: Settings = {}
  ) -> Sequence[OrderResponse | Exception]:
    """Place several orders, each as `place_order` does, one result per order."""
    results: list[OrderResponse | Exception] = []
    for offset in range(0, len(orders), BATCH):
      results.extend(await self.place_batch(orders[offset : offset + BATCH]))
    return results

  async def place_batch(
    self, orders: Sequence[Order]
  ) -> Sequence[OrderResponse | Exception]:
    """Place up to `BATCH` orders; the default sends them one by one."""
    return await super().place_orders(orders)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel one order and return KuCoin's acknowledgement.

    Raises:
      OrderNotFound: KuCoin answered that the order does not exist or already finished.
    """
    try:
      return await self.shared.call(lambda: self.cancel(id))
    except Error as exc:
      if not_found(exc):
        raise OrderNotFound(*exc.args) from exc
      raise

  async def query_order(self, id: str) -> OrderState | None:
    """Read one order of this symbol, finished ones too; `None` when KuCoin has none.

    Cancelled orders stay readable for days, not forever.
    """
    try:
      return await self.fetch_order(id)
    except Error as exc:
      if not_found(exc):
        return None
      raise

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to this symbol's fills from the account's private order channel.

    Fills carry the order and client order IDs and the liquidity role (the fee type
    charged), but no fee: KuCoin's order pushes do not report it. `trades_history`
    does. A dropped connection fails the stream with `NetworkError`; subscribing again
    reconnects.
    """
    return self.shared.stream(
      self.scope,
      lambda: connect_orders(self.shared, self.scope),
      select=self.event_trade,
      queue_size=queue_size,
      overflow=overflow,
    )
