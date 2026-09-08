"""Paged account history sweeps for one market.

Every page is fetched through `call_bybit`, so the retriable unit is the single
request that failed rather than the whole sweep -- a throttled page 7 of 12 retries
in place instead of restarting from page 1.
"""

from typing_extensions import AsyncIterator, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  FundingPayment,
  FundingRate,
  Trade,
  candle_windows,
)
from typed_bybit.schemas import KlineInterval

from tribulnation.bybit.core import TRADE_WINDOW, windows
from .mixin import MarketMixin
from .parse import parse_execution

FUNDING_PAGE = 200
"""Rows per `market.funding_history` page; Bybit's documented maximum."""

CANDLES_PAGE = 1000
"""Rows per `market.kline` page; Bybit's documented maximum."""

KLINE_INTERVALS: Mapping[CandleInterval, KlineInterval] = {
  '1m': '1',
  '5m': '5',
  '15m': '15',
  '1h': '60',
  '4h': '240',
  '1d': 'D',
}
"""Bybit's name for each contract interval: minutes, or `D` for a day."""

CANDLE_INTERVALS = frozenset(KLINE_INTERVALS)
"""Every contract interval has a Bybit kline interval."""

KlineRow = tuple[datetime, str, str, str, str, str, str]
"""One `market.kline` row: open time, open, high, low, close, volume, turnover."""


def parse_candle(row: KlineRow) -> Candle:
  """Map one kline row onto a `Candle`.

  `volume` is the base coin and `turnover` the quote coin on both spot and linear,
  which is the contract's own pairing.
  """
  time, open, high, low, close, volume, turnover = row
  return Candle(
    time=time,
    open=Decimal(open),
    high=Decimal(high),
    low=Decimal(low),
    close=Decimal(close),
    volume=Decimal(volume),
    quote_volume=Decimal(turnover),
  )


async def candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime | None,
  end: datetime | None,
) -> AsyncIterator[Sequence[Candle]]:
  """Walk this market's trade candles, oldest page first.

  Bybit answers newest-first, and at the start edge by bucket overlap: a candle
  already open at `start` is served too. With a `start`, the range is swept in forward
  windows of one page each, every window read through the client's own walk (so a
  short response is confirmed rather than trusted), reversed, and trimmed to the
  contract's own bounds. Without one, the whole backwards walk is buffered before the
  first page is yielded: ascending order needs the earliest page first, and only the
  venue knows where that is. An open `end` is resolved to now.
  """
  kline = KLINE_INTERVALS[interval]
  if end is None:
    end = datetime.now(timezone.utc)

  def walk(lower: datetime | None, upper: datetime):
    """The client's newest-first walk over `[lower, upper]`, one request per page."""
    return self.client.market.kline_paged(
      self.category,
      symbol=self.symbol,
      interval=kline,
      start=lower,
      end=upper,
      limit=CANDLES_PAGE,
      validate=self.validate,
    ).via(self.call_bybit)

  if start is None:
    pages = [rows async for rows in walk(None, end)]
    for rows in reversed(pages):
      yield [parse_candle(r) for r in reversed(rows)]
    return
  # One candle short of the cap, so the client's walk sees a short page and never
  # spends a request confirming a window is exhausted.
  for lower, upper in candle_windows(start, end, interval, size=CANDLES_PAGE - 1):
    rows = [r for r in await walk(lower, upper) if lower <= r[0] <= upper]
    if rows:
      yield [parse_candle(r) for r in sorted(rows, key=lambda r: r[0])]


async def trades_history(
  self: MarketMixin, start: datetime, end: datetime
) -> AsyncIterator[Sequence[Trade]]:
  """Walk this market's own fills, one cursor page at a time."""
  for lower, upper in windows(start, end, TRADE_WINDOW):
    cursor: str | None = None
    while True:
      page = await self.call_bybit(
        lambda: self.client.trade.trade_history(
          self.category,
          symbol=self.symbol,
          start_time=lower,
          end_time=upper,
          exec_type='Trade',
          cursor=cursor,
          validate=self.validate,
        )
      )
      yield [parse_execution(t) for t in page['list']]
      cursor = page.get('nextPageCursor')
      if not cursor:
        break


async def funding_rates(
  self: MarketMixin, start: datetime | None, end: datetime | None
) -> AsyncIterator[Sequence[FundingRate]]:
  """Walk this market's settled funding rates, newest page first.

  `market.funding_history` has no cursor -- it answers one time window with at most
  `limit` rows -- so the client's pager walks it backwards by moving the upper bound.

  An open upper bound is resolved to now rather than passed on: Bybit rejects a
  `startTime` sent without an `endTime` outright (`10001: Time Is Invalid`), while it
  answers an `endTime` with no `startTime` normally.
  """
  paging = self.client.market.funding_history_paged(
    'linear',
    symbol=self.symbol,
    start_time=start,
    end_time=end if end is not None else datetime.now(timezone.utc),
    limit=FUNDING_PAGE,
    validate=self.validate,
  )
  async for rows in paging.via(self.call_bybit):
    yield [
      FundingRate(rate=r['fundingRate'], time=r['fundingRateTimestamp']) for r in rows
    ]


async def funding_payments(
  self: MarketMixin, start: datetime, end: datetime
) -> AsyncIterator[Sequence[FundingPayment]]:
  """Walk this market's funding settlements out of the account transaction log.

  `account.transaction_log` has no symbol filter, so the rows are narrowed here.
  """
  for lower, upper in windows(start, end, TRADE_WINDOW):
    cursor: str | None = None
    while True:
      page = await self.call_bybit(
        lambda: self.client.account.transaction_log(
          category='linear',
          type='SETTLEMENT',
          start_time=lower,
          end_time=upper,
          cursor=cursor,
          validate=self.validate,
        )
      )
      yield [
        # A settlement charged to the account is money paid, which the SDK's
        # `FundingPayment` reports positive; Bybit signs `funding` the other way.
        FundingPayment(amount=-Decimal(e['funding']), time=e['transactionTime'])
        for e in page['list']
        if e['symbol'] == self.symbol and 'funding' in e and e['funding']
      ]
      cursor = page.get('nextPageCursor')
      if not cursor:
        break
