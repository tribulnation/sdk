"""Candles, funding rates, personal fills and funding payments, and the fills stream."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from typing_extensions import AsyncIterable, AsyncIterator, Literal, Mapping, Sequence
from typed_nado.schemas import Match
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

from ..core import Shared, wrap_exceptions, x18
from .common import parse_candle, parse_fill_event, parse_match

Granularity = Literal[60, 300, 900, 3600, 7200, 14400, 86400, 604800, 2419200]
GRANULARITIES: Mapping[CandleInterval, Granularity] = {
  '1m': 60,
  '5m': 300,
  '15m': 900,
  '1h': 3600,
  '4h': 14400,
  '1d': 86400,
}
"""The venue granularity (seconds) of each contract interval."""
CANDLE_INTERVALS = frozenset(GRANULARITIES)
CANDLE_PAGE = 500
"""Most candlesticks one request returns."""
FUNDING_PAGE = 1000
"""Most funding rates one request returns."""
MATCH_PAGE = 500
"""Most matches one request returns."""
PAYMENT_PAGE = 100
"""Funding payments requested per page."""
LAUNCH = datetime(2025, 1, 1, tzinfo=timezone.utc)
"""Before Nado's first market: where a funding-rate walk without `start` begins."""


async def candles(
  shared: Shared,
  product_id: int,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterable[Sequence[Candle]]:
  """Trade candles opening in `[start, end)`, newest first.

  The client walks back from `max_time` (inclusive); the walk stops at the first page
  reaching before `start`, and the exclusive `end` is applied locally.
  """
  if end <= start:
    return
  pages = shared.client.archive.candlesticks_paged(
    product_id=product_id,
    granularity=GRANULARITIES[interval],
    max_time=end,
    limit=CANDLE_PAGE,
  ).via(shared.call)
  async for page in pages:
    rows = [parse_candle(c) for c in page if start <= c['timestamp'] < end]
    if rows:
      yield rows
    if any(c['timestamp'] < start for c in page):
      return


async def funding_rates(
  shared: Shared, product_id: int, start: datetime | None, end: datetime | None
) -> AsyncIterable[Sequence[FundingRate]]:
  """Realized hourly rates with `start <= time <= end`, oldest first, positive when
  longs pay. These are per settlement already (unlike the predicted 24-hour rate)."""
  pages = shared.client.archive.funding_rate_history_paged(
    product_id=product_id,
    start_time=start or LAUNCH,
    end_time=end,
    limit=FUNDING_PAGE,
  ).via(shared.call)
  async for page in pages:
    rows = [
      FundingRate(rate=x18(r['funding_rate_x18']), time=r['timestamp'])
      for r in page
      if (start is None or start <= r['timestamp'])
      and (end is None or r['timestamp'] <= end)
    ]
    if rows:
      yield rows


async def matches(
  shared: Shared, product_ids: list[int] | None, start: datetime, end: datetime
) -> AsyncIterable[list[tuple[Match, datetime]]]:
  """The subaccount's fills with `start <= time <= end`, newest first, each with its
  transaction's time.

  Walked by hand with `idx` (inclusive) rather than `matches_paged`, which drops the
  `txs` a match's time comes from. Rows sharing the boundary `submission_idx` come
  back on the next page and are dropped by their (index, digest) key.
  """
  sender = shared.require_sender()
  idx: int | None = None
  seen: set[tuple[int, str]] = set()
  while True:
    page = await shared.call(
      lambda: shared.client.archive.matches(
        [sender],
        product_ids=product_ids,
        idx=idx,
        max_time=end,
        limit=MATCH_PAGE,
      )
    )
    times = {int(t['submission_idx']): t['timestamp'] for t in page['txs']}
    rows: list[tuple[Match, datetime]] = []
    older = False
    for m in page['matches']:
      key = (int(m['submission_idx']), m['digest'])
      if key in seen:
        continue
      seen.add(key)
      time = times[key[0]]
      if time < start:
        older = True
        continue
      if time <= end:
        rows.append((m, time))
    if rows:
      yield rows
    if older or not rows or len(page['matches']) < MATCH_PAGE:
      return
    idx = min(int(m['submission_idx']) for m in page['matches'])


async def trades_history(
  shared: Shared, product_id: int | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Personal fills of one product, newest first."""
  async for page in matches(
    shared, None if product_id is None else [product_id], start, end
  ):
    yield [parse_match(m, time) for m, time in page]


async def exchange_trades(
  shared: Shared, product_ids: list[int], start: datetime, end: datetime
) -> AsyncIterable[Sequence[ExchangeTrade]]:
  """Personal fills of several products (an exchange's), each with its symbol."""
  async for page in matches(shared, product_ids, start, end):
    rows: list[ExchangeTrade] = []
    for m, time in page:
      symbol = await shared.symbol_of(product_of(m))
      if symbol is None:
        continue
      rows.append(ExchangeTrade(**vars(parse_match(m, time)), market_id=symbol))
    if rows:
      yield rows


def product_of(m: Match) -> int:
  """The product a match traded: its balance entry's `product_id`."""
  base = m['post_balance']['base']
  return base['spot']['product_id'] if 'spot' in base else base['perp']['product_id']


async def funding_payments(
  shared: Shared, product_ids: list[int], start: datetime, end: datetime
) -> AsyncIterable[list[tuple[int, FundingPayment]]]:
  """Personal funding payments with `start <= time <= end`, newest first, with their
  product id; the venue's `amount` is already received-positive.

  `interest_and_funding` pages by `next_idx` and takes no time bound, so the walk
  skips rows after `end` and stops at the first one before `start`.
  """
  sender = shared.require_sender()
  max_idx: int | None = None
  while True:
    page = await shared.call(
      lambda: shared.client.archive.interest_and_funding(
        sender, product_ids=product_ids, max_idx=max_idx, limit=PAYMENT_PAGE
      )
    )
    rows: list[tuple[int, FundingPayment]] = []
    for p in page['funding_payments']:
      if p['timestamp'] < start:
        if rows:
          yield rows
        return
      if p['timestamp'] <= end:
        rows.append(
          (
            p['product_id'],
            FundingPayment(amount=x18(p['amount']), time=p['timestamp']),
          )
        )
    if rows:
      yield rows
    if page['next_idx'] is None or not page['funding_payments']:
      return
    max_idx = int(page['next_idx'])


async def market_funding_payments(
  shared: Shared, product_id: int, start: datetime, end: datetime
) -> AsyncIterable[Sequence[FundingPayment]]:
  """Personal funding payments of one perpetual."""
  async for page in funding_payments(shared, [product_id], start, end):
    yield [p for _, p in page]


async def exchange_funding_payments(
  shared: Shared, product_ids: list[int], start: datetime, end: datetime
) -> AsyncIterable[Sequence[ExchangeFundingPayment]]:
  """Personal funding payments of several perpetuals, each with its symbol."""
  async for page in funding_payments(shared, product_ids, start, end):
    rows: list[ExchangeFundingPayment] = []
    for pid, p in page:
      symbol = await shared.symbol_of(pid)
      if symbol is not None:
        rows.append(
          ExchangeFundingPayment(amount=p.amount, time=p.time, market_id=symbol)
        )
    if rows:
      yield rows


def fills_subscription(shared: Shared, product_id: int) -> Subscription[Trade]:
  """One `fill` feed per product, of the configured subaccount."""
  if product_id not in shared.fills:
    sender = shared.require_sender()

    @wrap_exceptions
    async def connect() -> Subscription.Context[Trade]:
      """Subscribe to the product's fills."""
      stream = await shared.client.streams.fill(sender, product_id=product_id)

      @wrap_exceptions
      async def trades() -> AsyncIterator[Trade]:
        """Each pushed fill."""
        async for fill in stream:
          yield parse_fill_event(fill)

      return Subscription.Context(trades(), wrap_exceptions(stream.unsubscribe))

    shared.fills[product_id] = Subscription(connect)
  return shared.fills[product_id]


@asynccontextmanager
async def trades_stream(
  shared: Shared,
  product_id: int,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
):
  """Fan out the subaccount's fills on one product.

  Args:
    shared: The owner of the client and its fan-outs.
    product_id: The product.
    queue_size: Fills buffered for this subscriber.
    overflow: What to do when the buffer is full.
  """
  shared.require_sender()
  source = fills_subscription(shared, product_id)
  async with source.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield stream
