"""Support for market integration tests."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tribulnation.sdk.market import Candle

START = datetime(2026, 6, 1, tzinfo=timezone.utc)
"""Open time of the first candle every case asks for.

A past day, so every candle in the windows below is closed and the counts are exact, in
a month every venue serves whole: a venue-side hole (Coinbase spot has none for
2026-05-08 02:00-06:00 UTC, five hours it never traded or never recorded) would fail
the exact counts, so a new hole means moving this, not loosening them.
"""

HOUR = timedelta(hours=1)

WINDOW = 72
"""Candles in the short window: three days of hourly candles."""

STRADDLE_EXTRA = 50
"""Candles past one page in the long window, so it must straddle two pages."""


@dataclass(frozen=True, kw_only=True)
class CandleCase:
  """One market the suite fetches hourly candles from."""

  market_id: str
  """The full `<account>:<exchange>:<market>` id, minus the account segment."""
  page: int
  """Candles per page the implementation yields, so the long window can be sized to
  straddle two of them."""


CASES: Mapping[str, Sequence[CandleCase]] = {
  'binance': [CandleCase(market_id='spot:BTCUSDT', page=1000)],
  # Spot is left out: its recent endpoint does not reach `START`; `bitget.py` covers it
  # over a recent window instead.
  'bitget': [CandleCase(market_id='perp:BTCUSDT', page=198)],
  'bybit': [
    CandleCase(market_id='spot:BTCUSDT', page=999),
    CandleCase(market_id='perp:BTCUSDT', page=999),
  ],
  'coinbase': [
    CandleCase(market_id='spot:BTC-USD', page=299),
    CandleCase(market_id='intx:BTC-PERP-INTX', page=299),
  ],
  'dydx': [CandleCase(market_id='perp:BTC-USD', page=999)],
  'mexc': [CandleCase(market_id='spot:BTCUSDT', page=500)],
}
"""The BTC market(s) to fetch per venue slug, for every venue implementing `candles`."""


@dataclass(frozen=True, kw_only=True)
class CandlesResult:
  """Result of fetching one market's hourly candles over a window."""

  pages: Sequence[Sequence[Candle]] | None = None
  failure: str | None = None

  @property
  def candles(self) -> list[Candle]:
    """Every candle across the pages, in the order they were yielded."""
    return [candle for page in self.pages or [] for candle in page]
