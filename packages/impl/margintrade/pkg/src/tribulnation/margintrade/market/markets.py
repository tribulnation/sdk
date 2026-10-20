"""The perpetual Market object; market ids are the venue's coin names (`'BTC'`)."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from typed_margintrade.schemas import PerpAssetCtx
from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Fees,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket,
  PerpPosition,
  Rules,
  Settings,
  Trade,
)

from ..core import FUNDING_INTERVAL, MAX_BAND, PRICE_DECIMALS, USDC
from . import account, books, history
from .common import Public, parse_open_order, parse_order

NOT_TRADED = 'Margin Trade trading is not implemented: no account trades there and no signed order has been verified.'


@dataclass(frozen=True, kw_only=True)
class MarginTradePerpMarket(Public, PerpMarket):
  """A perpetual market, margined and settled in USDC."""

  coin: str
  """The venue's coin name."""
  CANDLE_INTERVALS = history.CANDLE_INTERVALS

  @property
  def market_id(self) -> str:
    """The coin name."""
    return self.coin

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Price and size steps, the oracle price band and the market's standard rates.

    The price step is `10 ** -(6 - szDecimals)` and prices are also limited to 5
    significant figures, so the effective tick widens as the price rises. The band is
    `1 / (2 * maxLeverage)` of the oracle price, capped at 20%. Fees are the market's
    own `takerFee`/`makerFee`, which apply to every account (the venue lists no tiers).
    """
    m = await self.shared.asset(self.coin, refetch=refetch)
    band = min(Decimal(1) / (2 * m['maxLeverage']), MAX_BAND)
    return Rules(
      fee_asset=USDC,
      tick_size=Decimal(1).scaleb(-(PRICE_DECIMALS - m['szDecimals'])),
      step_size=Decimal(1).scaleb(-m['szDecimals']),
      rel_min_price=1 - band,
      rel_max_price=1 + band,
      fees=Fees.symmetric(maker=m['makerFee'], taker=m['takerFee']),
      api=not m.get('isDelisted', False),
      details=m,
    )

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """The venue's aggregated book snapshot."""
    return await books.depth(self.shared, self.coin, levels_cap=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Full-book snapshots from the shared `l2Book` channel."""
    return books.depth_stream(
      self.shared,
      self.coin,
      levels_cap=levels,
      queue_size=queue_size,
      overflow=overflow,
    )

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Trade candles opening in `[start, end)`, with base volume and trade counts."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      history.candles(self.shared, self.coin, interval, start, end)
    )

  async def query_order(self, id: str) -> OrderState | None:
    """Look an order up by venue order id. The venue resolves any account's order id,
    so an id from another account would be returned too; only this market's are."""
    status = await self.shared.call(
      lambda: self.shared.client.info.order_status(
        {'user': self.shared.user, 'oid': int(id)}
      )
    )
    if status['status'] == 'order' and status['order']['order']['coin'] == self.coin:
      return parse_order(status['order'])

  async def open_orders(self) -> Sequence[OrderState]:
    """The account's open orders on this market."""
    rows = await self.shared.call(
      lambda: self.shared.client.info.frontend_open_orders(self.shared.user)
    )
    return [parse_open_order(o) for o in rows if o['coin'] == self.coin]

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """The account's fills, fees in USDC (see `history` for the 10,000-fill limit)."""
    return PaginatedResponse(history.trades_history(self.shared, self.coin, start, end))

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Not supported: the venue's `userFills` channel pushed nothing to verify against."""
    raise NotImplementedError(
      f'Margin Trade fills streams are not implemented: {self.id}'
    )

  async def perp_position(self) -> PerpPosition:
    """The signed position and average entry."""
    state = await self.shared.call(
      lambda: self.shared.client.info.clearinghouse_state(self.shared.user)
    )
    return account.perp_position(state, self.coin)

  async def perp_collateral(self) -> PerpCollateral:
    """This market's isolated bucket when its position is isolated, else cross."""
    state = await self.shared.call(
      lambda: self.shared.client.info.clearinghouse_state(self.shared.user)
    )
    return account.market_collateral(state, self.coin)

  async def leverage(self, *, refetch: bool = False) -> Decimal:
    """The account's leverage setting on this market (`activeAssetData`), cached."""
    cached = self.shared.leverages.get(self.coin)
    if cached is not None and not refetch:
      return cached
    data = await self.shared.call(
      lambda: self.shared.client.info.active_asset_data(
        user=self.shared.user, coin=self.coin
      )
    )
    leverage = Decimal(data['leverage']['value'])
    self.shared.leverages[self.coin] = leverage
    return leverage

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """The oracle price, from `metaAndAssetCtxs`."""
    ctx = await self.context()
    return ctx['oraclePx']

  async def next_funding(self) -> NextFunding:
    """The current hourly funding rate, settled at the top of the next hour."""
    ctx = await self.context()
    return NextFunding(
      rate=ctx['funding'],
      time=next_hour(datetime.now(timezone.utc)),
      premium=ctx['premium'],
      interval=FUNDING_INTERVAL,
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Not supported: the venue's `fundingHistory` returns no rows."""
    raise NotImplementedError(
      f'Margin Trade funding-rate history is empty upstream: {self.id}'
    )

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """The account's funding payments, received-positive."""
    return PaginatedResponse(
      history.funding_payments(self.shared, self.coin, start, end)
    )

  async def context(self) -> PerpAssetCtx:
    """This market's live context from `metaAndAssetCtxs`.

    Raises:
      ValueError: The coin is not a listed perpetual.
    """
    meta, contexts = await self.shared.call(self.shared.client.info.meta_and_asset_ctxs)
    for item, ctx in zip(meta['universe'], contexts):
      if item['name'] == self.coin:
        return ctx
    raise ValueError(f'Unknown Margin Trade perpetual market: {self.coin!r}')

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Not supported (see `NOT_TRADED`)."""
    raise NotImplementedError(NOT_TRADED)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Not supported (see `NOT_TRADED`)."""
    raise NotImplementedError(NOT_TRADED)


def next_hour(now: datetime) -> datetime:
  """The top of the hour after `now`."""
  return now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL
