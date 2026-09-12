"""Historical trade candles for one product, read off the public catalog."""

from typing_extensions import AsyncIterable, Literal, Mapping, Sequence
from datetime import datetime, timedelta
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
  start: datetime,
  end: datetime,
) -> AsyncIterable[Sequence[Candle]]:
  """Read bounded windows in native order, filtering each to `[lower, upper)`.

  Coinbase refuses large ranges, so windows remain necessary even without sorting.
  Buckets with no trades are absent, not zero.
  """
  granularity = GRANULARITIES[interval]
  # Reserve one slot for a boundary bucket, whether the venue includes it or the
  # whole-second wire precision broadens the range. Each window fits one response.
  for lower, upper in candle_windows(start, end, interval, size=CANDLES_PAGE - 1):
    response = await self.call_app(
      lambda: self.app.advanced_trade.http.products.public.candles(
        self.product_id,
        start=lower,
        end=upper + timedelta(seconds=1),
        granularity=granularity,
        limit=CANDLES_PAGE,
      )
    )
    page = [parse_candle(r) for r in response['candles'] if lower <= r['start'] < upper]
    if page:
      yield page
