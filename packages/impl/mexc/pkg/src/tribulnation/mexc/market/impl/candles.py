"""Historical trade candles for one spot symbol."""

from typing_extensions import AsyncIterable, Literal, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.market import Candle, CandleInterval

from tribulnation.mexc.core.exc import wrap_exceptions
from .mixin import MarketMixin

CANDLES_PAGE = 500
"""Rows per `klines` page.

MEXC documents a 1000-row maximum but serves 500 whatever `limit` says (verified live
with `limit` 600 and 1000), and the client's walk stops on the first page shorter than
the `limit` it sent, so asking for more would silently end the sweep after one page.
"""

MILLISECOND = timedelta(milliseconds=1)
"""MEXC timestamps are epoch milliseconds, so this is one indivisible step."""

MexcInterval = Literal['1m', '5m', '15m', '30m', '60m', '4h', '1d', '1W', '1M']

MEXC_INTERVALS: Mapping[CandleInterval, MexcInterval] = {
  '1m': '1m',
  '5m': '5m',
  '15m': '15m',
  '1h': '60m',
  '4h': '4h',
  '1d': '1d',
}
"""MEXC's name for each contract interval; only the hour is spelt differently."""

CANDLE_INTERVALS = frozenset(MEXC_INTERVALS)
"""Every contract interval has a MEXC kline interval."""

KlineRow = tuple[datetime, str, str, str, str, str, datetime, str]
"""One `klines` row: open time, open, high, low, close, volume, close time, quote volume."""


def parse_candle(row: KlineRow) -> Candle:
  """Map one kline row onto a `Candle`."""
  time, open, high, low, close, volume, _, quote_volume = row
  return Candle(
    time=time,
    open=Decimal(open),
    high=Decimal(high),
    low=Decimal(low),
    close=Decimal(close),
    volume=Decimal(volume),
    quote_volume=Decimal(quote_volume),
  )


@wrap_exceptions
async def candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime | None,
  end: datetime | None,
) -> AsyncIterable[Sequence[Candle]]:
  """Walk this symbol's trade candles, oldest page first.

  MEXC walks forwards on its own, but bounds `endTime` exclusively on open time, so
  the contract's inclusive `end` is passed one millisecond later. An open `start` is
  refused: without a `startTime` the venue answers its most recent page, and an
  epoch-zero one answers nothing at all, so there is no way to ask for the earliest.
  """
  if start is None:
    raise ValueError(
      f'MEXC serves candles only from an explicit start [{self.instrument}]: an '
      'unbounded request answers the latest page, not the earliest.'
    )
  paging = self.client.spot.http.market.candles_paged(
    self.instrument,
    interval=MEXC_INTERVALS[interval],
    start_time=start,
    end_time=end + MILLISECOND if end is not None else None,
    limit=CANDLES_PAGE,
    validate=self.shared.validate,
  )
  async for rows in paging.via(self.call_mexc):
    yield [parse_candle(r) for r in rows]
