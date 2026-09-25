"""Personal fills and funding, public funding rates and candles, and the fills stream."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from typing_extensions import (
  AsyncIterable,
  AsyncIterator,
  Callable,
  Literal,
  Mapping,
  Sequence,
)
from typed_lighter.schemas import Trade as TradeRow
from tribulnation.sdk.core import OverflowPolicy, Subscription, exception_wrapper
from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  FundingRate,
  Trade,
  candle_width,
  candle_windows,
)
from tribulnation.sdk.market.types.candles import EPOCH

from ..core import FUNDING_INTERVAL, USDC, Shared, percent
from .common import parse_candle, parse_trade, role

TRADES_PAGE = 100
"""Trades per `trades` request."""
FUNDING_PAGE = 100
"""Payments per `position_funding` request."""

RESOLUTIONS: Mapping[CandleInterval, Literal['1m', '5m', '15m', '1h', '4h', '1d']] = {
  '1m': '1m',
  '5m': '5m',
  '15m': '15m',
  '1h': '1h',
  '4h': '4h',
  '1d': '1d',
}
"""The venue's resolution for each contract interval."""
CANDLE_INTERVALS = frozenset(RESOLUTIONS)

Fee = Callable[[TradeRow, int], Trade.Fee]
"""A market kind's fee rule: the account's fee on a trade, in its asset."""


def perp_fee(t: TradeRow, account: int) -> Trade.Fee:
  """Perpetual fees are the role's rate on the USDC notional."""
  _, _, rate = role(t, account)
  return Trade.Fee(amount=t['usd_amount'] * rate, asset=str(USDC))


def spot_fee(
  base_asset: Callable[[int], int], quote_asset: Callable[[int], int]
) -> Fee:
  """Spot fees are charged in the received asset: base on a buy, quote on a sell.

  Args:
    base_asset: The base asset id of a market id.
    quote_asset: The quote asset id of a market id.
  """

  def fee(t: TradeRow, account: int) -> Trade.Fee:
    """The role's rate on the amount received."""
    is_ask, _, rate = role(t, account)
    if is_ask:
      return Trade.Fee(
        amount=t['size'] * t['price'] * rate, asset=str(quote_asset(t['market_id']))
      )
    return Trade.Fee(amount=t['size'] * rate, asset=str(base_asset(t['market_id'])))

  return fee


async def trades_history(
  shared: Shared,
  market_type: Literal['perp', 'spot'],
  market_id: int | None,
  start: datetime,
  end: datetime,
  *,
  fee: Fee,
) -> AsyncIterable[Sequence[Trade]]:
  """Personal fills with `start <= time <= end`, newest first; exchange-wide rows are
  `ExchangeTrade`s. Paging stops at the first fill older than `start`."""
  account = shared.account_index
  pages = shared.client.api.account.orders.trades_paged(
    'timestamp',
    limit=TRADES_PAGE,
    account_index=account,
    market_type=market_type,
    market_id=market_id,
  ).via(shared.call)
  async for page in pages:
    rows: list[Trade] = []
    for t in page:
      if t['timestamp'] > end:
        continue
      if t['timestamp'] < start:
        if rows:
          yield rows
        return
      trade = parse_trade(t, account, fee(t, account))
      rows.append(
        trade
        if market_id is not None
        else ExchangeTrade(**vars(trade), market_id=str(t['market_id']))
      )
    if rows:
      yield rows


def fills_subscription(shared: Shared, market_id: int, fee: Fee) -> Subscription[Trade]:
  """One `account_market` feed per market, yielding the account's new fills."""
  if market_id not in shared.fills:
    account = shared.account_index

    @exception_wrapper()
    async def connect() -> Subscription.Context[Trade]:
      """Subscribe; the snapshot frame replays existing state and is skipped."""
      stream = await shared.client.streams.account_market(
        market_id=market_id, account_index=account
      )

      @exception_wrapper()
      async def fills() -> AsyncIterator[Trade]:
        """Each update's new trades."""
        async for frame in stream:
          if frame['type'] == 'subscribed/account_market':
            continue
          for t in frame['trades']:
            yield parse_trade(t, account, fee(t, account))

      return Subscription.Context(fills(), exception_wrapper()(stream.unsubscribe))

    shared.fills[market_id] = Subscription(connect)
  return shared.fills[market_id]


@asynccontextmanager
async def trades_stream(
  shared: Shared,
  market_id: int,
  *,
  fee: Fee,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
):
  """Fan out the account's fills on one market."""
  source = fills_subscription(shared, market_id, fee)
  async with source.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield stream


def grid_start(start: datetime, width: timedelta) -> datetime:
  """The first grid point at or after `start`: candles opening at or after it are
  exactly those opening at or after `start`."""
  offset = (start - EPOCH) % width
  return start if not offset else start - offset + width


CANDLES_PAGE = 500
"""Most candles one `candles` response holds (the newest ones of a wider range)."""


async def candles(
  shared: Shared,
  market_id: int,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterable[Sequence[Candle]]:
  """Candles opening in `[start, end)`, oldest window first, one request per window.

  The venue's CDN caches `candles` responses without `start_timestamp` in the key: a
  request sharing `end_timestamp` and `count_back` with an earlier one is answered with
  the earlier range's rows. Each window therefore asks for exactly its own number of grid
  opens as `count_back`, which (with the window's end) identifies it. Windows start on
  the interval's grid, and are at most one response long. Where the venue has fewer
  candles than asked for, it extends the range backwards; rows outside the window are
  dropped.
  """
  width = candle_width(interval)
  for lower, upper in candle_windows(start, end, interval, size=CANDLES_PAGE):
    lower = grid_start(lower, width)
    count = -((lower - upper) // width)
    if count <= 0:
      continue
    response = await shared.call(
      lambda: shared.client.api.markets.candles(
        market_id=market_id,
        resolution=RESOLUTIONS[interval],
        start_timestamp=lower,
        end_timestamp=upper,
        count_back=count,
      )
    )
    rows = [
      parse_candle(c)
      for c in response['c']
      if lower <= c['t'] < upper and start <= c['t'] < end
    ]
    if rows:
      yield rows


async def funding_rates(
  shared: Shared, market_id: int, start: datetime | None, end: datetime | None
) -> AsyncIterable[Sequence[FundingRate]]:
  """Hourly settlements with `start <= time <= end`.

  The venue's `rate` is unsigned, in percent, with `direction` naming the side that
  paid (`long`: positive). Its bounds are exclusive and hour-granular, so the request
  spans one interval more on each side, from the hour, and the bounds apply locally.
  """
  detail = await shared.perp(market_id)
  lower = start or detail['created_at']
  upper = end or datetime.now(timezone.utc)
  hour = grid_start(lower.astimezone(timezone.utc), FUNDING_INTERVAL)
  pages = shared.client.api.markets.fundings_paged(
    market_id=market_id,
    resolution='1h',
    start_timestamp=hour - 2 * FUNDING_INTERVAL,
    end_timestamp=upper + FUNDING_INTERVAL,
    count_back=0,
  ).via(shared.call)
  async for page in pages:
    rows = [
      FundingRate(
        rate=percent(f['rate']) if f['direction'] == 'long' else -percent(f['rate']),
        time=f['timestamp'],
      )
      for f in page
      if lower <= f['timestamp'] <= upper
    ]
    if rows:
      yield rows


async def funding_payments(
  shared: Shared, market_id: int | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[FundingPayment]]:
  """Personal payments with `start <= time <= end`, newest first; the venue's
  received-positive `change` becomes the SDK's paid-positive amount. The request window
  is widened by one interval, as for `funding_rates`."""
  account = shared.account_index
  pages = shared.client.api.account.position_funding_paged(
    account_index=account,
    limit=FUNDING_PAGE,
    start_timestamp=start - FUNDING_INTERVAL,
    end_timestamp=end + FUNDING_INTERVAL,
    market_ids=None if market_id is None else [market_id],
  ).via(shared.call)
  async for page in pages:
    rows: list[FundingPayment] = []
    for f in page:
      if not start <= f['timestamp'] <= end:
        continue
      if market_id is None:
        rows.append(
          ExchangeFundingPayment(
            amount=-f['change'], time=f['timestamp'], market_id=str(f['market_id'])
          )
        )
      else:
        rows.append(FundingPayment(amount=-f['change'], time=f['timestamp']))
    if rows:
      yield rows
