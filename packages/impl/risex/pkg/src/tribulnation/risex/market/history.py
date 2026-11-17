"""Candles, funding rates and payments, personal fills, the fills stream and the
funding estimate."""

from contextlib import asynccontextmanager
from datetime import datetime

from typing_extensions import (
  AsyncIterable,
  AsyncIterator,
  Collection,
  Mapping,
  Sequence,
)
from typed_risex.streams.expected_funding_rate import ExpectedFundingRate
from typed_risex.streams.fills import FillsMessage
from tribulnation.sdk.core import NetworkError, OverflowPolicy, Subscription
from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  FundingRate,
  Trade,
  candle_width,
)

from ..core import Shared, wrap_exceptions
from .common import funding_received, parse_trade

CANDLE_SECONDS: Mapping[CandleInterval, int] = {
  '1m': 60,
  '5m': 300,
  '15m': 900,
  '1h': 3600,
  '4h': 14400,
  '1d': 86400,
}
"""Each contract interval's width. The venue takes a nanosecond duration and serves
these at their width (mainnet, 2026-11-17); a width it does not serve (`3m`, `30m`,
`2h`, ...) silently comes back as 1-minute candles."""
CANDLE_INTERVALS = frozenset(CANDLE_SECONDS)
CANDLES_CHUNK = 10_000
"""Intervals per candles request: one request returns its whole range, but the venue
rejects a range over 86,400 intervals (`time range is not valid`)."""
PAGE = 1000
"""Rows per history page, the venue's maximum."""
NS = 10**9


async def candles(
  shared: Shared,
  market_id: int,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterable[Sequence[Candle]]:
  """Trade candles opening in `[start, end)`, oldest first, one page per chunk of
  `CANDLES_CHUNK` intervals; volume is in the base asset."""
  width = candle_width(interval)
  lower = start
  while lower < end:
    upper = min(lower + width * CANDLES_CHUNK, end)
    first, last = lower, upper
    raw = await shared.call(
      lambda: shared.client.markets.candles(
        market_id=market_id,
        interval=CANDLE_SECONDS[interval] * NS,
        from_=first,
        to=last,
      )
    )
    rows = [
      Candle(
        time=c['time'],
        open=c['open'],
        high=c['high'],
        low=c['low'],
        close=c['close'],
        volume=c['volume'],
      )
      for c in raw['data']
      if first <= c['time'] < last
    ]
    if rows:
      yield rows
    lower = upper


async def funding_rates(
  shared: Shared, market_id: int, start: datetime | None, end: datetime | None
) -> AsyncIterable[Sequence[FundingRate]]:
  """Applied hourly rates with `start <= time <= end`, newest first, stamped with the
  settlement (`end_time` of the hour); positive rates are paid by longs."""
  pages = shared.client.markets.funding_rate_history_paged(
    market_id=market_id, start_time=start, end_time=end, limit=PAGE
  ).via(shared.call)
  async for page in pages:
    rows = [
      FundingRate(rate=r['funding_rate'], time=r['end_time'])
      for r in page
      if (start is None or start <= r['end_time'])
      and (end is None or r['end_time'] <= end)
    ]
    if rows:
      yield rows


async def funding_payments(
  shared: Shared, market_id: int | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[FundingPayment]]:
  """The account's hourly funding with `start <= time <= end`, newest first, positive
  when received, in USDC; exchange-wide rows are `ExchangeFundingPayment`s.

  Accruals not yet settled into the balance (a position still open) are included.

  Raises:
    ValueError: A bound is not timezone-aware.
  """
  if start.tzinfo is None or end.tzinfo is None:
    raise ValueError('Funding history bounds must be timezone-aware')
  account = shared.require_account()
  pages = shared.client.account.funding_payments_paged(
    account, market_id=market_id, start_time=start, end_time=end, limit=PAGE
  ).via(shared.call)
  async for page in pages:
    rows: list[FundingPayment] = []
    for r in page:
      if not start <= r['block_time'] <= end:
        continue
      amount = funding_received(r)
      rows.append(
        FundingPayment(amount=amount, time=r['block_time'])
        if market_id is not None
        else ExchangeFundingPayment(
          amount=amount, time=r['block_time'], market_id=str(r['market_id'])
        )
      )
    if rows:
      yield rows


async def trades_history(
  shared: Shared, market_id: int | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """The account's fills with `start <= time <= end`, newest first; exchange-wide rows
  are `ExchangeTrade`s."""
  account = shared.require_account()
  pages = shared.client.account.trade_history_paged(
    account, market_id=market_id, start_time=start, end_time=end, limit=PAGE
  ).via(shared.call)
  async for page in pages:
    rows: list[Trade] = []
    for t in page:
      if not start <= t['time'] <= end:
        continue
      trade = parse_trade(t)
      rows.append(
        trade
        if market_id is not None
        else ExchangeTrade(**vars(trade), market_id=str(t['market_id']))
      )
    if rows:
      yield rows


def fills_subscription(shared: Shared) -> Subscription[FillsMessage]:
  """The account's one fills upstream, every market: a client holds one subscription
  per channel, so markets share it and filter."""
  account = shared.require_account()
  if account not in shared.fills:

    @wrap_exceptions
    async def connect() -> Subscription.Context[FillsMessage]:
      """Subscribe; the client authenticates the connection with the signer key."""
      stream = await shared.client.streams.fills()

      @wrap_exceptions
      async def frames() -> AsyncIterator[FillsMessage]:
        """Every fill frame of the account."""
        async for frame in stream:
          yield frame

      return Subscription.Context(frames(), wrap_exceptions(stream.unsubscribe))

    shared.fills[account] = Subscription(connect)
  return shared.fills[account]


@asynccontextmanager
async def trades_stream(
  shared: Shared,
  market_id: int,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
):
  """Fan out the account's new fills, filtered to one market.

  The bounded queue holds every market's fills, since they share one upstream.

  Raises:
    AuthError: The client has no signer key.
  """
  shared.require_signer()
  await shared.market(market_id)
  source = fills_subscription(shared)

  async def fills(stream: AsyncIterable[FillsMessage]) -> AsyncIterator[Trade]:
    """The market's fills, as `Trade`s."""
    async for frame in stream:
      if frame['market_id'] == market_id:
        yield parse_trade(frame['data'])

  async with source.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield fills(stream)


async def expected_funding(
  shared: Shared, market_ids: Collection[int]
) -> dict[int, ExpectedFundingRate]:
  """The venue's estimate of each market's next hourly rate, from the first frame of
  the public `expected_funding_rate` stream, on a dedicated connection.

  `markets.all`'s `current_funding_rate` is not it: it equals the rate last applied.

  Raises:
    NetworkError: The stream closed before its first frame.
  """
  async with shared.public_client() as own:
    async with own.streams.expected_funding_rate(list(market_ids)) as stream:
      async for frame in stream:
        return {r['market_id']: r for r in frame['data']}
  raise NetworkError('RISEx expected_funding_rate stream closed before its first frame')
