"""Candles, funding rates, personal fills and funding payments, and the fills stream.

Every history endpoint walks newest first by cursor, and applies its time bounds
inclusively, in nanoseconds. An inclusive upper bound goes out one microsecond later
(`core.upper_bound`) and the caller's bounds are then applied locally.
"""

from contextlib import asynccontextmanager
from datetime import datetime

from typing_extensions import AsyncIterable, AsyncIterator, Mapping, Sequence
from typed_grvt.schemas import CandlestickInterval
from tribulnation.sdk.core import OverflowPolicy, Subscription
from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  FundingRate,
  Trade,
)

from ..core import Shared, percent, upper_bound, wrap_exceptions
from .common import parse_candle, parse_fill, scope

PAGE = 1000
"""Rows per request: the most every history endpoint returns."""

INTERVALS: Mapping[CandleInterval, CandlestickInterval] = {
  '1m': 'CI_1_M',
  '5m': 'CI_5_M',
  '15m': 'CI_15_M',
  '1h': 'CI_1_H',
  '4h': 'CI_4_H',
  '1d': 'CI_1_D',
}
"""The venue's interval for each contract interval."""
CANDLE_INTERVALS = frozenset(INTERVALS)


async def candles(
  shared: Shared,
  instrument: str,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterable[Sequence[Candle]]:
  """Trade candles opening in `[start, end)`, newest first.

  The client walks pages by moving `end_time` to the oldest open received. The venue's
  bounds are inclusive on open time at both ends, so the exclusive `end` is applied
  locally.
  """
  if end <= start:
    return
  pages = shared.client.market.candlesticks_paged(
    instrument,
    interval=INTERVALS[interval],
    type='TRADE',
    start_time=start,
    end_time=end,
    limit=PAGE,
  ).via(shared.call)
  async for page in pages:
    rows = [parse_candle(c) for c in page if start <= c['open_time'] < end]
    if rows:
      yield rows


async def funding_rates(
  shared: Shared, instrument: str, start: datetime | None, end: datetime | None
) -> AsyncIterable[Sequence[FundingRate]]:
  """Settled rates with `start <= time <= end`, newest first, as fractions.

  Rows with `funding_interval_hours == 0` are dropped: up to mid-October 2025 the venue
  recorded one per minute (BTC's last at 2025-10-15 08:00 UTC), and they are not
  settlements. A walk without `start` still reads through every one of them.
  """
  pages = shared.client.market.funding_rate_paged(
    instrument=instrument,
    start_time=start,
    end_time=None if end is None else upper_bound(end),
    limit=PAGE,
  ).via(shared.call)
  async for page in pages:
    rows = [
      FundingRate(rate=percent(r['funding_rate']), time=r['funding_time'])
      for r in page
      if r['funding_interval_hours']
      and (start is None or start <= r['funding_time'])
      and (end is None or r['funding_time'] <= end)
    ]
    if rows:
      yield rows


async def trades_history(
  shared: Shared, instrument: str | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Personal perpetual fills with `start <= time <= end`, newest first.

  One market is filtered by its base and quote; exchange-wide rows (`instrument=None`)
  are `ExchangeTrade`s.
  """
  shared.require_session()
  if instrument is None:
    pages = shared.client.trading.fill_history_paged(
      kind=['PERPETUAL'], start_time=start, end_time=upper_bound(end), limit=PAGE
    )
  else:
    base, quote = scope(await shared.instrument(instrument))
    pages = shared.client.trading.fill_history_paged(
      kind=['PERPETUAL'],
      base=base,
      quote=quote,
      start_time=start,
      end_time=upper_bound(end),
      limit=PAGE,
    )
  async for page in pages.via(shared.call):
    rows: list[Trade] = []
    for f in page:
      if not start <= f['event_time'] <= end:
        continue
      if instrument is None:
        rows.append(ExchangeTrade(**vars(parse_fill(f)), market_id=f['instrument']))
      elif f['instrument'] == instrument:
        rows.append(parse_fill(f))
    if rows:
      yield rows


async def funding_payments(
  shared: Shared, instrument: str | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[FundingPayment]]:
  """Personal funding payments with `start <= time <= end`, newest first.

  The venue's `amount` is positive when paid (its own documentation), so it is negated
  into the SDK's received-positive cash flow (ADR 0035). Exchange-wide rows
  (`instrument=None`) are `ExchangeFundingPayment`s.
  """
  shared.require_session()
  if instrument is None:
    pages = shared.client.trading.funding_payment_history_paged(
      kind=['PERPETUAL'], start_time=start, end_time=upper_bound(end), limit=PAGE
    )
  else:
    pages = shared.client.trading.funding_payment_history_paged(
      instrument=instrument,
      start_time=start,
      end_time=upper_bound(end),
      limit=PAGE,
    )
  async for page in pages.via(shared.call):
    rows: list[FundingPayment] = []
    for p in page:
      if not start <= p['event_time'] <= end:
        continue
      if instrument is None:
        rows.append(
          ExchangeFundingPayment(
            amount=-p['amount'], time=p['event_time'], market_id=p['instrument']
          )
        )
      else:
        rows.append(FundingPayment(amount=-p['amount'], time=p['event_time']))
    if rows:
      yield rows


def fills_subscription(shared: Shared, instrument: str) -> Subscription[Trade]:
  """One `v1.fill` feed per instrument (of the client's trading sub-account), pushing
  the same `Fill` the history returns."""
  if instrument not in shared.fills:

    @wrap_exceptions
    async def connect() -> Subscription.Context[Trade]:
      """Subscribe to the instrument's fills."""
      stream = await shared.client.trading_streams.fills(instrument=instrument)

      @wrap_exceptions
      async def trades() -> AsyncIterator[Trade]:
        """Each pushed fill."""
        async for fill in stream:
          yield parse_fill(fill)

      return Subscription.Context(trades(), wrap_exceptions(stream.unsubscribe))

    shared.fills[instrument] = Subscription(connect)
  return shared.fills[instrument]


@asynccontextmanager
async def trades_stream(
  shared: Shared,
  instrument: str,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
):
  """Fan out the account's fills on one perpetual.

  Args:
    shared: The owner of the client and its fan-outs.
    instrument: The instrument name.
    queue_size: Fills buffered for this subscriber.
    overflow: What to do when the buffer is full.
  """
  shared.require_session()
  source = fills_subscription(shared, instrument)
  async with source.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield stream
