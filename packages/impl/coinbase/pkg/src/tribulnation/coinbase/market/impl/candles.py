"""Historical trade candles for one product, read off the public catalog."""

from typing_extensions import AsyncIterable, Literal, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.sdk.market import Candle, CandleInterval, candle_windows

from typed_coinbase.schemas import Candle as CandleRow

from .mixin import MarketMixin

CANDLES_PAGE = 300
"""Candles per `candles` request: the most every Coinbase product answers whole.

The documented cap is 350, and spot honours it: a range holding one more is refused
(`INVALID_ARGUMENT`), and at exactly 351 the oldest is dropped instead. INTX
perpetuals answer at most 300 whatever `limit` says, silently dropping the oldest of a
wider range -- all verified live -- so a range is swept in windows of this size.
"""

Granularity = Literal[
  'ONE_MINUTE',
  'FIVE_MINUTE',
  'FIFTEEN_MINUTE',
  'THIRTY_MINUTE',
  'ONE_HOUR',
  'TWO_HOUR',
  'FOUR_HOUR',
  'SIX_HOUR',
  'ONE_DAY',
]

GRANULARITIES: Mapping[CandleInterval, Granularity] = {
  '1m': 'ONE_MINUTE',
  '5m': 'FIVE_MINUTE',
  '15m': 'FIFTEEN_MINUTE',
  '1h': 'ONE_HOUR',
  '4h': 'FOUR_HOUR',
  '1d': 'ONE_DAY',
}
"""Coinbase's granularity name for each contract interval."""

CANDLE_INTERVALS = frozenset(GRANULARITIES)
"""Every contract interval has a Coinbase granularity."""


def parse_candle(row: CandleRow) -> Candle:
  """Map one candle bucket onto a `Candle`. Coinbase reports base volume only."""
  return Candle(
    time=row['start'],
    open=Decimal(row['open']),
    high=Decimal(row['high']),
    low=Decimal(row['low']),
    close=Decimal(row['close']),
    volume=row['volume'],
  )


async def candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime | None,
  end: datetime | None,
) -> AsyncIterable[Sequence[Candle]]:
  """Walk this product's trade candles, oldest page first.

  Coinbase answers newest-first and only one page per range, so the range is swept in
  forward windows of one page each, every window read through the client's own walk
  (so a short response is confirmed rather than trusted), reversed, and trimmed to the
  contract's own bounds: the venue takes whole seconds, so a `start` inside one is
  rounded down on the wire. An open `start` is refused, since the venue serves no
  range wider than a page and publishes no listing date to count forward from. An open
  `end` is resolved to now. Buckets with no trades are absent, not zero.
  """
  if start is None:
    raise ValueError(
      f'Coinbase serves candles only from an explicit start [{self.product_id}]: it '
      'answers one page per request and publishes no listing date.'
    )
  if end is None:
    end = datetime.now(timezone.utc)
  granularity = GRANULARITIES[interval]
  # One candle short of the cap, so the client's walk sees a short page and never
  # spends a request confirming a window is exhausted.
  for lower, upper in candle_windows(start, end, interval, size=CANDLES_PAGE - 1):
    paging = self.app.advanced_trade.http.products.public.candles_paged(
      self.product_id,
      start=lower,
      end=upper,
      granularity=granularity,
      limit=CANDLES_PAGE,
    )
    rows = [r for r in await paging.via(self.call_app) if lower <= r['start'] <= upper]
    if rows:
      yield [parse_candle(r) for r in sorted(rows, key=lambda r: r['start'])]
