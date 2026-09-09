"""Support for market integration tests."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tribulnation.sdk.market import Candle

END = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
  minute=0,
  second=0,
  microsecond=0,
)
"""A rolling, closed-hour boundary safely inside recent-history retention."""

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
  page: int | None
  """Candles per page the implementation yields, so the long window can be sized to
  straddle two of them."""


CASES: Mapping[str, Sequence[CandleCase]] = {
  'binance': [
    CandleCase(market_id='spot:BTCUSDT', page=1000),
    CandleCase(market_id='usdm:BTCUSDT', page=1000),
  ],
  'bitget': [
    CandleCase(market_id='spot:BTCUSDT', page=999),
    CandleCase(market_id='perp:BTCUSDT', page=198),
  ],
  'bit2me': [CandleCase(market_id='spot:BTC/EUR', page=998)],
  # The retained 5000 opens fit one response; asking for 5050 cannot prove paging.
  'hyperliquid': [
    CandleCase(market_id=':BTC', page=None),
    CandleCase(market_id='spot:UBTC/USDC:142', page=None),
  ],
  'bybit': [
    CandleCase(market_id='spot:BTCUSDT', page=999),
    CandleCase(market_id='perp:BTCUSDT', page=999),
  ],
  'coinbase': [
    CandleCase(market_id='spot:BTC-USD', page=299),
    CandleCase(market_id='intx:BTC-PERP-INTX', page=299),
  ],
  'dydx': [CandleCase(market_id='perp:BTC-USD', page=999)],
  'mexc': [
    CandleCase(market_id='spot:BTCUSDT', page=500),
    CandleCase(market_id='perp:BTC_USDT', page=2000),
  ],
  # Kraken retains 720 rows and cannot page into older history.
  'kraken': [CandleCase(market_id='spot:XBTUSD', page=None)],
}
"""The BTC market(s) to fetch per venue slug, for every venue implementing `candles`."""


@dataclass(frozen=True, kw_only=True)
class CandlesResult:
  """Result of fetching one market's hourly candles over a window."""

  pages: Sequence[Sequence[Candle]] | None = None
  failure: str | None = None
  start: datetime = END - WINDOW * HOUR
  end: datetime = END

  @property
  def candles(self) -> list[Candle]:
    """Every candle across the pages, in the order they were yielded."""
    return [candle for page in self.pages or [] for candle in page]
