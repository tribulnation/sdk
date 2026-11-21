"""Bitget's cross spot-margin pairs on a Unified Trading Account (UTA)."""

from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncGenerator,
  AsyncIterable,
  AsyncIterator,
  Literal,
  Sequence,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Fees,
  InterestPayment,
  MarginMarket as _MarginMarket,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  Position,
  Rules,
  Settings,
  Trade,
)

from .impl import (
  CANDLE_INTERVALS,
  MarketMixin,
  depth_stream,
  interest_pair,
  interest_payments,
  open_orders,
  parse_book,
  spot_candles,
  trades_history,
  trades_stream,
  uta_perp_collateral,
)
from .impl import trading
from .impl.account import margin_position
from .impl.parse import MARGIN, PERP, perp_exchange_id, parse_margin_rules

DEFAULT_LEVERAGE = Decimal(1)
"""`leverage()` when the account lists no cross setting for the pair: the most
conservative multiple, so free collateral is never over-committed."""


@dataclass(kw_only=True, frozen=True)
class MarginMarket(MarketMixin, _MarginMarket):
  """One UTA cross spot-margin pair, e.g. `LITUSDT`, under the `margin` exchange.

  It trades the spot pair's book in category `MARGIN`: a sell of more base than the
  unified pool holds auto-borrows the rest at placement, and buys repay that debt
  (the account's `repayMode: auto`). The position is the pool's net base-coin
  holding, negative when borrowed and sold (see `impl.account.margin_exposure`), and
  the collateral is the same unified pool that margins the perpetuals, so
  `collateral_id()` names that pool. A Classic account raises `NotImplementedError`
  on every account read and order.
  """

  CANDLE_INTERVALS = CANDLE_INTERVALS

  @property
  def product(self) -> Literal['MARGIN']:
    """`MARGIN`, the UTA category orders, fills and fees are addressed under."""
    return MARGIN

  @property
  def market_id(self) -> str:
    return self.symbol

  @property
  def exchange_id(self) -> str:
    return 'margin'

  async def require_uta(self):
    """Refuse a Classic account, whose margin wallets this adapter does not read.

    Raises:
      NotImplementedError: The account is in Classic mode.
    """
    if not await self.is_uta():
      raise NotImplementedError(
        'Bitget spot margin is implemented for Unified Trading Accounts only.'
      )

  async def base_coin(self) -> str:
    """The pair's base coin, e.g. `LIT`."""
    instruments = await self.margin_instruments()
    return instruments[self.symbol]['baseCoin']

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """Fetch the pair's spot order book (150 levels a side when `levels` is omitted)."""
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
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the pair's spot order book, shared with the spot market: margin
    has no book of its own."""
    return depth_stream(self, levels=levels, queue_size=queue_size, overflow=overflow)

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Fetch the pair's margin trading rules from the public instrument catalogue.

    Args:
      refetch: Refetch the catalogue instead of reading the cached one.
    """
    instruments = await self.margin_instruments(refetch=refetch)
    return parse_margin_rules(instruments[self.symbol])

  def candles(
    self,
    interval: CandleInterval,
    start: datetime,
    end: datetime,
  ) -> PaginatedResponse[Candle]:
    """Fetch the spot pair's candles with opening timestamps in `[start, end)`."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(spot_candles(self, interval, start, end))

  async def open_orders(self) -> Sequence[OrderState]:
    """Fetch your currently open margin orders on the pair."""
    await self.require_uta()
    return await open_orders(self)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Fetch your margin fills on the pair."""

    async def pages() -> AsyncIterator[Sequence[Trade]]:
      await self.require_uta()
      async for page in trades_history(self, start, end):
        yield page

    return PaginatedResponse(pages())

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time margin fills on the pair (UTA `fill` channel,
    category `margin`)."""
    return self.uta_trades_stream(queue_size=queue_size, overflow=overflow)

  @asynccontextmanager
  async def uta_trades_stream(
    self, *, queue_size: int, overflow: OverflowPolicy
  ) -> AsyncGenerator[AsyncIterable[Trade]]:
    """`trades_stream`, refused on a Classic account before subscribing."""
    await self.require_uta()
    async with trades_stream(self, queue_size=queue_size, overflow=overflow) as s:
      yield s

  async def position(self, *, ttl: timedelta | None = None) -> Position:
    """Fetch your net base-coin holding: owned less borrowed, negative when short.

    It is the unified pool's whole balance of the coin, so a spot holding of the same
    coin on this account counts too: it is the same exposure. Every margin pair of
    the coin (`LINKUSDT`, `LINKUSDC`) reads this same figure, and each must, since a
    strategy trading either one sizes from it: count it once per account and coin,
    not once per pair. The spot markets read only what the pool owns (0 for a
    borrowed-and-sold short). Accrued interest is in the debt, so it is in here.
    """
    await self.require_uta()
    return await margin_position(self, await self.base_coin())

  async def collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """Fetch the unified pool backing the pair, as for the perpetuals: one cross pool
    across every product line, so its figures are never counted per product."""
    await self.require_uta()
    return await uta_perp_collateral(self)

  async def collateral_id(self) -> str:
    """The unified pool, `<account_id>:usdt`: the same ID the `usdt` perpetuals
    return, since orders on either draw on the same money. No request is made."""
    return f'{self.account_id}:{perp_exchange_id(PERP)}'

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """The cross leverage the account lists for the pair, else `DEFAULT_LEVERAGE`.

    Bitget lists a symbol's leverage only once it has been set; rather than guess the
    venue's default, an unlisted pair answers 1, which never commits more than the
    free collateral.
    """
    await self.require_uta()
    settings = await self.call(
      lambda: self.client.uta.account.settings(validate=self.validate)
    )
    rows = [
      Decimal(c['leverage'])
      for c in settings['symbolConfigList']
      if c['symbol'] == self.symbol
      and c['category'].upper() == MARGIN
      and c['marginMode'] == 'crossed'
    ]
    return rows[0] if rows else DEFAULT_LEVERAGE

  def interest_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[InterestPayment]:
    """Fetch the interest charged on the pair's base coin: the UTA ledger's
    `INTEREST_SETTLEMENT_OUT` rows for it, in base units, negative when paid.

    Debt in the coin is pool-wide, so interest on it counts here whichever pair or
    product borrowed it, and only one pair of the coin reports it (`interest_pair`:
    the USDT-quoted one); the others answer nothing, so a sum over margin markets
    counts each charge once. Interest on borrowed USDT (the quote) is the pool's:
    `MarginExchange.interest_payments(None, ...)`.

    Bitget adds interest to the debt, so `position()` already includes it: add these
    rows to fill-based P&L, not to a mark-to-market of `position()`.
    """

    async def pages() -> AsyncIterator[Sequence[InterestPayment]]:
      await self.require_uta()
      instruments = await self.margin_instruments()
      coin = instruments[self.symbol]['baseCoin']
      if interest_pair(instruments, coin) == self.symbol:
        async for page in interest_payments(self, start, end, coin=coin):
          yield page

    return PaginatedResponse(pages())

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Read this account's margin rates for the pair (UTA `fee-rate`, `MARGIN`)."""
    await self.require_uta()
    return await super().fees(refetch=refetch)

  def random_client_order_id(self) -> str:
    """A fresh 32-character client order ID, Bitget's maximum."""
    return uuid4().hex

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place a margin order, auto-borrowing what a sell lacks; see
    `impl.trading.place_order`."""
    return await trading.place_order(self, order, settings=settings)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel an order; see `impl.trading.cancel_order`."""
    return await trading.cancel_order(self, id)

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel every open margin order on the pair in one request."""
    return await trading.cancel_open_orders(self)

  async def replace_order(
    self, id: str, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Cancel order `id` and place `order`; see `impl.trading.replace_order`."""
    return await trading.replace_order(self, id, order, settings=settings)

  async def query_order(self, id: str) -> OrderState | None:
    """The state of an order, resting or done; see `impl.trading.query_order`."""
    return await trading.query_order(self, id)
