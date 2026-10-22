"""Candles, funding rates, personal fills and the account's fills stream."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from typing_extensions import AsyncIterable, AsyncIterator, Literal, Mapping, Sequence
from tribulnation.sdk.core import OverflowPolicy, Subscription, exception_wrapper
from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  ExchangeTrade,
  FundingRate,
  Trade,
  candle_width,
)
from tribulnation.sdk.market.types.candles import EPOCH

from ..core import COLLATERAL, Shared
from .common import parse_candle, parse_trade

INTERVALS: Mapping[
  CandleInterval, Literal['PT1M', 'PT5M', 'PT15M', 'PT1H', 'PT4H', 'P1D']
] = {
  '1m': 'PT1M',
  '5m': 'PT5M',
  '15m': 'PT15M',
  '1h': 'PT1H',
  '4h': 'PT4H',
  '1d': 'P1D',
}
"""The venue's interval for each contract interval."""
CANDLE_INTERVALS = frozenset(INTERVALS)
CANDLES_PAGE = 1000
"""Most opens one candle request asks for (the venue serves up to 2800)."""
TRADES_PAGE = 100
"""Fills per `trades` request."""
LAUNCH = datetime(2024, 1, 1, tzinfo=timezone.utc)
"""Before Extended's first market: the default funding-rates start when the market
reports no creation time."""


def grid_start(start: datetime, interval: CandleInterval) -> datetime:
  """The first open of `interval`'s grid at or after `start`."""
  width = candle_width(interval)
  offset = (start - EPOCH) % width
  return start if not offset else start - offset + width


async def candles(
  shared: Shared,
  market: str,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterable[Sequence[Candle]]:
  """Trade candles opening in `[start, end)`, newest first.

  The client's walk starts at `end` (exclusive) with `limit` the window's number of grid
  opens, at most `CANDLES_PAGE`, and moves `end` back to each page's oldest open. It stops
  once a page reaches the window's first open; older rows are dropped.
  """
  first = grid_start(start, interval)
  count = -((first - end) // candle_width(interval))
  if count <= 0:
    return
  pages = shared.client.info.candles_paged(
    market,
    candle_type='trades',
    interval=INTERVALS[interval],
    limit=min(count, CANDLES_PAGE),
    end_time=end,
  ).via(shared.call)
  async for page in pages:
    rows = [parse_candle(c) for c in page if start <= c['T'] < end]
    if rows:
      yield rows
    if not page or min(c['T'] for c in page) <= first:
      return


async def funding_rates(
  shared: Shared, market: str, start: datetime | None, end: datetime | None
) -> AsyncIterable[Sequence[FundingRate]]:
  """Applied hourly rates with `start <= time <= end`, newest first.

  Rates are fractions, positive when longs pay. `start=None` starts at the market's
  creation; `end=None` is now.
  """
  if start is None:
    row = await shared.perp(market)
    start = row.get('createdAt') or LAUNCH
  upper = end or datetime.now(timezone.utc)
  pages = shared.client.info.funding_rates_paged(
    market, start_time=start, end_time=upper
  ).via(shared.call)
  async for page in pages:
    if page:
      yield [FundingRate(rate=r['f'], time=r['T']) for r in page]


async def trades_history(
  shared: Shared, market: str | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Personal perpetual fills with `start <= time <= end`, newest first.

  `account.trades` lists spot and perpetual fills together, at most the 10,000 most
  recent, with no time filter: pages are read until a fill precedes `start`. The
  exchange-wide form leaves out fills on markets the venue lists as spot and returns
  `ExchangeTrade`s; delisted perpetuals are included.
  """
  markets = await shared.load_markets()
  pages = shared.client.account.trades_paged(
    None if market is None else [market], limit=TRADES_PAGE
  ).via(shared.call)
  async for page in pages:
    rows: list[Trade] = []
    for t in page:
      if t['createdTime'] > end:
        continue
      if t['createdTime'] < start:
        if rows:
          yield rows
        return
      row = markets.get(t['market'])
      if row is not None and row['type'] == 'SPOT':
        continue
      fee_asset = row['collateralAssetName'] if row is not None else COLLATERAL
      trade = parse_trade(t, fee_asset)
      rows.append(
        trade
        if market is not None
        else ExchangeTrade(**vars(trade), market_id=t['market'])
      )
    if rows:
      yield rows


def fills_subscription(
  shared: Shared, market: str, fee_asset: str
) -> Subscription[Trade]:
  """One account stream per market, yielding the account's new fills on it."""
  if market not in shared.fills:

    @exception_wrapper()
    async def connect() -> Subscription.Context[Trade]:
      """Subscribe; the first frames are snapshots of orders, positions and balances."""
      stream = await shared.client.streams.account()

      @exception_wrapper()
      async def fills() -> AsyncIterator[Trade]:
        """Each `TRADE` frame's fills on this market."""
        async for frame in stream:
          data = frame.get('data')
          if frame['type'] != 'TRADE' or data is None:
            continue
          for t in data.get('trades', []):
            if t['market'] == market:
              yield parse_trade(t, fee_asset)

      return Subscription.Context(fills(), exception_wrapper()(stream.unsubscribe))

    shared.fills[market] = Subscription(connect)
  return shared.fills[market]


@asynccontextmanager
async def trades_stream(
  shared: Shared,
  market: str,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
):
  """Fan out the account's fills on one market, with fees in its collateral asset."""
  row = await shared.perp(market)
  source = fills_subscription(shared, market, row['collateralAssetName'])
  async with source.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield stream
