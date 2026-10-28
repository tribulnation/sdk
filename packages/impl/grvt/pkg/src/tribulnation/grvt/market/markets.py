"""The perpetual and spot Market objects; market ids are GRVT instrument names
(`BTC_USDT_Perp`, `GRVT_USDT_SpotSwap`)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Fees,
  FundingPayment,
  FundingRate,
  Market,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket,
  PerpPosition,
  Rules,
  Settings,
  SpotBalances,
  SpotMarket,
  SpotRules,
  Trade,
)

from ..core import random_client_order_id
from . import account, books, history, orders, stats
from .common import Public

STANDARD_FEES = Fees.symmetric(maker=Decimal('-0.000001'), taker=Decimal('0.00045'))
"""Tier 1 of GRVT's published perpetual schedule (help.grvt.io, "How does Grvt's Fee
Model work?", read 2026-10-22: maker -0.0001%, taker 0.0450%), which the API also reports
as tier 1 (`-1`/`450` millionths). Account tiers are `fees()`."""


@dataclass(frozen=True, kw_only=True)
class OrderBookMarket(Public, Market):
  """An instrument on GRVT's order book: books, candles, orders and fills are the same
  endpoints for perpetuals and spot."""

  instrument: str
  """The instrument name, the market id."""
  CANDLE_INTERVALS = history.CANDLE_INTERVALS

  @property
  def market_id(self) -> str:
    """The instrument name."""
    return self.instrument

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """The aggregated book at the smallest venue depth (10, 50, 100 or 500 levels per
    side) covering `levels`; 500 when `levels` is `None`."""
    return await books.depth(self.shared, self.instrument, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """The full book from `v1.book.d` (snapshot, then 50 ms deltas), shared by every
    consumer of the market."""
    return books.depth_stream(
      self.shared,
      self.instrument,
      levels=levels,
      queue_size=queue_size,
      overflow=overflow,
    )

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Trade candles opening in `[start, end)`, newest first, up to 1000 per page."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      history.candles(self.shared, self.instrument, interval, start, end)
    )

  async def query_order(self, id: str) -> OrderState | None:
    """Look the order up by client order id."""
    return await orders.query_order(self.shared, self.instrument, id)

  async def open_orders(self) -> Sequence[OrderState]:
    """The market's open orders."""
    return await orders.open_orders(self.shared, self.instrument)

  def random_client_order_id(self) -> str:
    """A fresh client order id in `[2^63, 2^64)`, the range GRVT reserves for API
    clients."""
    return random_client_order_id()

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place a `MARKET` (the venue's immediate-or-cancel market order, `price` not
    sent), `LIMIT` or `POST_ONLY` order (good-till-time, expiring 29 days after
    signing); the id is its client order id.

    Raises:
      AuthError: The client has no private key to sign with.
      OrderRejected: The venue refused the order before accepting it (off-tick price,
        size off the step, below the minimum notional, margin or balance, ...).
    """
    return await orders.place_order(self.shared, self.instrument, order)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel by client order id."""
    return await orders.cancel_order(self.shared, id)

  async def cancel_orders(self, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Cancel by client order ids, 100 per request."""
    return await orders.cancel_orders(self.shared, ids)

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """The venue's cancel-all, scoped to this market."""
    return await orders.cancel_open_orders(self.shared, self.instrument)

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """The account's new fills on this market."""
    return history.trades_stream(
      self.shared, self.instrument, queue_size=queue_size, overflow=overflow
    )


@dataclass(frozen=True, kw_only=True)
class GrvtPerpMarket(OrderBookMarket, PerpMarket):
  """A USDT-margined perpetual."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def rules(self, *, refetch: bool = False) -> Rules:
    """The instrument's tick, size step (`min_size`, also the minimum) and minimum
    notional, with the published tier-1 rates; fees are charged in the quote (USDT).
    `max_position_size` caps a position, not an order, and stays in `details`."""
    i = await self.shared.instrument(self.instrument, kind='PERPETUAL', refetch=refetch)
    return Rules(
      fee_asset=i['quote'],
      tick_size=i['tick_size'],
      step_size=i['min_size'],
      fixed_min_qty=i['min_size'],
      min_value=i['min_notional'],
      fees=STANDARD_FEES,
      api=i.get('status') == 'ACTIVE',
      details=i,
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account tier's futures rates, the same for every perpetual and both sides."""
    return await account.fees(self.shared)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Personal fills, with fees in USDT."""
    return PaginatedResponse(
      history.trades_history(self.shared, self.instrument, start, end, kind='PERPETUAL')
    )

  async def perp_position(self, *, ttl: timedelta | None = None) -> PerpPosition:
    """The signed position and average entry."""
    return await account.perp_position(self.shared, self.instrument)

  async def perp_collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """The isolated position's own bucket where the market holds one, else the cross
    bucket."""
    return account.market_bucket(await account.summary(self.shared), self.instrument)

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """The account's initial leverage on this market."""
    return await account.leverage(self.shared, self.instrument, ttl=ttl)

  async def collateral_id(self) -> str:
    """The trading sub-account's cross pool, `<account_id>:<exchange_id>`: it funds
    isolated positions too, whose margin moves out of it when they open."""
    return f'{self.account_id}:{self.exchange_id}'

  async def available_notional(self, *, ttl: timedelta | None = None) -> Decimal:
    """Free cross collateral (`margin_balance` less the cross initial margin) times
    `leverage()`, without the venue's position-size cap or risk brackets.

    The cross pool funds isolated positions too (their margin is moved out of it when
    they open), so an isolated market is sized against it as well.
    """
    leverage = await self.leverage(ttl=ttl)
    return (
      account.cross_bucket(await account.summary(self.shared)).free_collateral
      * leverage
    )

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """The index price."""
    return await stats.index(self.shared, self.instrument)

  async def next_funding(self, *, ttl: timedelta | None = None) -> NextFunding:
    """The indicative rate of the current interval, positive when longs pay."""
    return await stats.next_funding(self.shared, self.instrument)

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Settled rates, newest first, positive when longs pay."""
    return PaginatedResponse(
      history.funding_rates(self.shared, self.instrument, start, end)
    )

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Personal funding payments, received-positive."""
    return PaginatedResponse(
      history.funding_payments(self.shared, self.instrument, start, end)
    )


@dataclass(frozen=True, kw_only=True)
class GrvtSpotMarket(OrderBookMarket, SpotMarket):
  """A spot instrument (`SPOT_SWAP`), settled in the trading sub-account's spot wallet."""

  @property
  def exchange_id(self) -> str:
    """The spot exchange."""
    return 'spot'

  async def rules(self, *, refetch: bool = False) -> SpotRules:
    """The instrument's tick, size step (`min_size`, also the minimum), minimum
    notional and currencies.

    The fee is charged in the asset a fill delivers (base on a buy, quote on a sell),
    so `fee_asset` is `None`; GRVT publishes no standard spot schedule, so `fees` is
    `None` too (account rates are `fees()`).
    """
    i = await self.shared.instrument(self.instrument, kind='SPOT_SWAP', refetch=refetch)
    return SpotRules(
      base=i['base'],
      quote=i['quote'],
      fee_asset=None,
      tick_size=i['tick_size'],
      step_size=i['min_size'],
      fixed_min_qty=i['min_size'],
      min_value=i['min_notional'],
      fees=None,
      api=i.get('status') == 'ACTIVE',
      details=i,
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account tier's spot rates, the same for every spot instrument and both
    sides."""
    return await account.spot_fees(self.shared)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Personal fills, each with its fee in the asset it delivered."""
    return PaginatedResponse(
      history.trades_history(self.shared, self.instrument, start, end, kind='SPOT_SWAP')
    )

  async def balances(self, *, ttl: timedelta | None = None) -> SpotBalances:
    """The base and quote spot-wallet balances, from one `spot_account_summary`.

    `free` is the venue's `available_to_transfer`; whether it excludes what open spot
    orders hold is unverified.
    """
    i = await self.shared.instrument(self.instrument, kind='SPOT_SWAP')
    rows = await account.spot_wallet(self.shared, ttl=ttl)
    return SpotBalances(
      base=account.spot_balance(rows, i['base']),
      quote=account.spot_balance(rows, i['quote']),
    )
