"""Validated TradingView candles over the venue's working public WebSocket transport."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import AsyncIterator, Literal
from typed_deribit.market_data.get_tradingview_chart_data import TradingviewChartData
from tribulnation.sdk.market import Candle, CandleInterval
from tribulnation.sdk.market.types.candles import candle_windows
from .common import Shared

RESOLUTIONS: dict[CandleInterval, Literal['1', '5', '15', '60']] = {
  '1m': '1',
  '5m': '5',
  '15m': '15',
  '1h': '60',
}
CANDLE_INTERVALS = frozenset(RESOLUTIONS)
PAGE_SIZE = 1000
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def inclusive_end(end: datetime) -> datetime:
  """Last representable millisecond strictly before an exclusive SDK boundary."""
  rounded = end.replace(microsecond=end.microsecond // 1000 * 1000)
  return rounded - timedelta(milliseconds=1) if rounded == end else rounded


def parse_candles(row: TradingviewChartData) -> list[Candle]:
  """Check parallel arrays before mapping native OHLC and base/quote volumes."""
  if row.get('status') == 'no_data':
    if any(
      row.get(key)
      for key in ('ticks', 'open', 'high', 'low', 'close', 'volume', 'cost')
    ):
      raise ValueError('Deribit no_data candle response contains rows')
    return []
  if row.get('status') != 'ok':
    raise ValueError('Deribit candle response has no recognized status')
  ticks = row.get('ticks')
  opens, highs, lows, closes = (
    row.get('open'),
    row.get('high'),
    row.get('low'),
    row.get('close'),
  )
  if ticks is None or opens is None or highs is None or lows is None or closes is None:
    raise ValueError('Deribit candle response is missing required arrays')
  volumes, costs = row.get('volume'), row.get('cost')
  if any(
    len(values) != len(ticks)
    for values in (opens, highs, lows, closes, volumes, costs)
    if values is not None
  ):
    raise ValueError('Deribit candle arrays have unequal lengths')
  return [
    Candle(
      time=EPOCH + timedelta(milliseconds=t),
      open=Decimal(str(opens[i])),
      high=Decimal(str(highs[i])),
      low=Decimal(str(lows[i])),
      close=Decimal(str(closes[i])),
      volume=None if volumes is None else Decimal(str(volumes[i])),
      quote_volume=None if costs is None else Decimal(str(costs[i])),
    )
    for i, t in enumerate(ticks)
  ]


async def candles(
  shared: Shared, symbol: str, interval: CandleInterval, start: datetime, end: datetime
) -> AsyncIterator[list[Candle]]:
  """Walk bounded time windows, including empty windows, without synthetic candles."""
  for lower, upper in candle_windows(start, end, interval, size=PAGE_SIZE):
    row = await shared.call(
      lambda: shared.client.market_data.get_tradingview_chart_data(
        symbol,
        start_timestamp=lower,
        end_timestamp=inclusive_end(upper),
        resolution=RESOLUTIONS[interval],
        transport='ws',
      )
    )
    seen: set[datetime] = set()
    page: list[Candle] = []
    for candle in parse_candles(row):
      if lower <= candle.time < upper and candle.time not in seen:
        seen.add(candle.time)
        page.append(candle)
    yield page
