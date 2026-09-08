"""Unit tests for `Market.candles`: interval validation, the lifted mirrors on
`Exchange`/`TradingVenue`/`TradingMarkets`, and the window arithmetic implementations
share.
"""

from typing_extensions import Any, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  Exchange,
  Market,
  TradingMarkets,
  TradingVenue,
  candle_windows,
)

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def candle(hours: int) -> Candle:
  """A flat candle opening `hours` after `T0`."""
  price = Decimal(60_000 + hours)
  return Candle(time=T0 + hours * HOUR, open=price, high=price, low=price, close=price)


PAGES: list[list[Candle]] = [[candle(0), candle(1)], [candle(2)]]


@dataclass(frozen=True)
class FakeMarket(Market):
  """A market serving `PAGES` for hourly candles and nothing else."""

  CANDLE_INTERVALS = frozenset[CandleInterval]({'1h'})

  calls: list[tuple[CandleInterval, datetime | None, datetime | None]]

  @property
  def market_id(self) -> str:
    return 'BTCUSDT'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def venue_id(self) -> str:
    return 'fake'

  def candles(
    self,
    interval: CandleInterval,
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> PaginatedResponse[Candle]:
    self.check_interval(interval)
    self.calls.append((interval, start, end))

    async def pages() -> AsyncIterable[Sequence[Candle]]:
      for page in PAGES:
        yield page

    return PaginatedResponse(pages())

  async def depth(self, *, levels: int | None = None) -> Any:
    raise NotImplementedError

  def depth_stream(self, **kwargs: Any) -> Any:
    raise NotImplementedError

  async def rules(self, *, refetch: bool = False) -> Any:
    raise NotImplementedError

  async def open_orders(self) -> Any:
    raise NotImplementedError

  def trades_history(self, start: datetime, end: datetime) -> Any:
    raise NotImplementedError

  def trades_stream(self, **kwargs: Any) -> Any:
    raise NotImplementedError

  async def position(self) -> Any:
    raise NotImplementedError

  async def collateral(self) -> Any:
    raise NotImplementedError

  async def available_notional(self) -> Any:
    raise NotImplementedError

  async def place_order(self, order: Any, *, settings: Any = {}) -> Any:
    raise NotImplementedError

  async def cancel_order(self, id: str, *, settings: Any = {}) -> Any:
    raise NotImplementedError


@dataclass(frozen=True)
class FakeExchange(Exchange):
  """An exchange handing out one `FakeMarket`."""

  fake: FakeMarket

  @property
  def venue_id(self) -> str:
    return 'fake'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def market(self, market_id: str, /) -> Market:
    return self.fake

  async def markets(self) -> Sequence[str]:
    return [self.fake.market_id]

  async def tickers(self, markets: Any = None, *, settings: Any = {}) -> Any:
    raise NotImplementedError


@dataclass(frozen=True)
class FakeVenue(TradingVenue):
  """A venue with one spot exchange."""

  fake: FakeExchange

  @property
  def venue_id(self) -> str:
    return 'fake'

  async def exchange(self, exchange_id: str, /) -> Exchange:
    return self.fake

  async def exchanges(self) -> Any:
    return [{'id': 'spot', 'type': 'spot'}]


@dataclass(frozen=True)
class FakeMarkets(TradingMarkets):
  """A routing root with one venue."""

  fake: FakeVenue

  async def venue(self, id: str, /) -> TradingVenue:
    return self.fake

  async def venues(self) -> Sequence[str]:
    return ['fake']


def fixture() -> tuple[FakeMarket, FakeExchange, FakeVenue, FakeMarkets]:
  """One market wrapped by an exchange, a venue and a routing root."""
  market = FakeMarket(calls=[])
  exchange = FakeExchange(fake=market)
  venue = FakeVenue(fake=exchange)
  return market, exchange, venue, FakeMarkets(fake=venue)


def test_check_interval_names_the_market_and_what_it_serves():
  """An interval outside `CANDLE_INTERVALS` is refused before any request."""
  market, *_ = fixture()
  with pytest.raises(ValueError, match=r"'5m'.*fake:spot:BTCUSDT.*1h"):
    market.candles('5m')
  assert market.calls == []


async def test_market_candles_is_awaitable_and_iterable():
  """The market's own response flattens on await and pages on iteration."""
  market, *_ = fixture()
  assert await market.candles('1h', T0, T0 + 2 * HOUR) == [c for p in PAGES for c in p]
  pages = [page async for page in market.candles('1h')]
  assert pages == PAGES
  assert market.calls == [('1h', T0, T0 + 2 * HOUR), ('1h', None, None)]


async def test_exchange_lifts_candles_with_a_leading_market_id():
  """`Exchange.candles` routes to the market and keeps the pages intact."""
  market, exchange, *_ = fixture()
  pages = [page async for page in exchange.candles('BTCUSDT', '1h', T0)]
  assert pages == PAGES
  assert await exchange.candles('BTCUSDT', '1h') == [c for p in PAGES for c in p]
  assert market.calls == [('1h', T0, None), ('1h', None, None)]


async def test_venue_and_root_lift_candles_the_same_way():
  """`TradingVenue` and `TradingMarkets` mirror the method with the longer ids."""
  market, _, venue, root = fixture()
  assert [p async for p in venue.candles('spot:BTCUSDT', '1h', end=T0)] == PAGES
  assert [p async for p in root.candles('fake:spot:BTCUSDT', '1h', T0, T0)] == PAGES
  assert market.calls == [('1h', None, T0), ('1h', T0, T0)]


async def test_lifted_interval_errors_surface_on_iteration():
  """The mirrors look the market up lazily, so the refusal arrives on first use."""
  _, exchange, *_ = fixture()
  with pytest.raises(ValueError, match="'1d'"):
    await exchange.candles('BTCUSDT', '1d')


def test_candle_windows_are_aligned_and_abut():
  """Windows hold at most `size` candles, share no open time, and leave no gap."""
  windows = list(candle_windows(T0, T0 + 1049 * HOUR, '1h', size=1000))
  assert windows == [
    (T0, T0 + 999 * HOUR),
    (T0 + 1000 * HOUR, T0 + 1049 * HOUR),
  ]


def test_candle_windows_keep_a_misaligned_start_off_the_grid_boundary():
  """A start inside a candle shortens the first window rather than shifting the grid.

  Shifting it would put a window boundary mid-candle, and a venue that answers by
  bucket overlap would then serve that candle in both windows.
  """
  start = T0 + timedelta(minutes=30)
  windows = list(candle_windows(start, T0 + 12 * HOUR, '4h', size=2))
  assert windows == [
    (start, T0 + 4 * HOUR),
    (T0 + 8 * HOUR, T0 + 12 * HOUR),
  ]


def test_candle_windows_clip_to_the_end_and_cover_a_single_candle():
  """`end` bounds the last window, and `start == end` is one window of one candle."""
  assert list(candle_windows(T0, T0, '1d', size=10)) == [(T0, T0)]
  assert list(candle_windows(T0, T0 - HOUR, '1d', size=10)) == []
