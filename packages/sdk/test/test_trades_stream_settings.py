"""`trades_stream` takes venue-keyed `settings`, forwarded unchanged to the market."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from typing_extensions import Any, AsyncIterator, Sequence
import inspect

import pytest

from tribulnation.sdk.impl.accounts import VenueId
from tribulnation.sdk.market import (
  Exchange,
  Market,
  Settings,
  Trade,
  TradingMarkets,
  TradingVenue,
)


@dataclass(frozen=True)
class RecordingMarket(Market):
  """A market recording the `settings` of every `trades_stream`."""

  calls: list[Settings] = field(default_factory=list[Settings])

  @property
  def market_id(self) -> str:
    return 'BTC-USD'

  @property
  def exchange_id(self) -> str:
    return 'perp'

  @property
  def venue_id(self) -> VenueId:
    return 'dydx'

  @property
  def account_id(self) -> str:
    return 'fake'

  @asynccontextmanager
  async def trades_stream(
    self, *, queue_size: int = 1000, overflow: Any = 'fail', settings: Settings = {}
  ):
    self.calls.append(settings)

    async def gen() -> AsyncIterator[Trade]:
      return
      yield

    yield gen()

  async def place_order(self, order: Any, *, settings: Any = {}) -> Any:
    raise NotImplementedError

  async def depth(self, *, levels: int | None = None, settings: Any = {}) -> Any:
    raise NotImplementedError

  def depth_stream(self, **kwargs: Any) -> Any:
    raise NotImplementedError

  async def rules(self, *, refetch: bool = False) -> Any:
    raise NotImplementedError

  def candles(self, interval: Any, start: datetime, end: datetime) -> Any:
    raise NotImplementedError

  async def open_orders(self) -> Any:
    raise NotImplementedError

  def trades_history(self, start: datetime, end: datetime) -> Any:
    raise NotImplementedError

  async def position(self) -> Any:
    raise NotImplementedError

  async def collateral(self) -> Any:
    raise NotImplementedError

  async def available_notional(self) -> Any:
    raise NotImplementedError

  async def cancel_order(self, id: str, *, settings: Any = {}) -> Any:
    raise NotImplementedError


@dataclass(frozen=True)
class OneMarketExchange(Exchange):
  """An exchange with one market."""

  only: RecordingMarket

  @property
  def venue_id(self) -> VenueId:
    return 'dydx'

  @property
  def account_id(self) -> str:
    return 'fake'

  @property
  def exchange_id(self) -> str:
    return 'perp'

  async def market(self, market_id: str, /) -> Market:
    return self.only

  async def markets(self) -> Sequence[str]:
    return ['BTC-USD']

  async def tickers(self, markets: Any = None, *, settings: Any = {}) -> Any:
    raise NotImplementedError


@dataclass(frozen=True)
class OneExchangeVenue(TradingVenue):
  """A venue with one exchange."""

  only: OneMarketExchange

  @property
  def venue_id(self) -> VenueId:
    return 'dydx'

  @property
  def account_id(self) -> str:
    return 'fake'

  async def exchange(self, exchange_id: str, /) -> Exchange:
    return self.only

  async def exchanges(self) -> Any:
    return [{'id': 'perp', 'type': 'perp'}]


@dataclass(frozen=True)
class OneVenueMarkets(TradingMarkets):
  """A routing root with one venue."""

  only: OneExchangeVenue

  async def venue(self, id: str, /) -> TradingVenue:
    return self.only

  async def venues(self) -> Sequence[str]:
    return ['fake']


async def test_routing_forwards_trades_stream_settings():
  """The root, venue and exchange wrappers pass `settings` through, empty by default."""
  market = RecordingMarket()
  exchange = OneMarketExchange(only=market)
  venue = OneExchangeVenue(only=exchange)
  root = OneVenueMarkets(only=venue)
  settings: Settings = {'dydx': {'trades_source': 'fastest'}}
  async with root.trades_stream('fake:perp:BTC-USD'):
    pass
  async with root.trades_stream('fake:perp:BTC-USD', settings=settings):
    pass
  async with venue.trades_stream('perp:BTC-USD', settings=settings):
    pass
  async with exchange.trades_stream('BTC-USD', settings=settings):
    pass
  assert market.calls == [{}, settings, settings, settings]


VENUE_MARKETS = [
  ('tribulnation.aster.market.markets', 'NativeMarket'),
  ('tribulnation.binance.market.perp_market', 'PerpMarket'),
  ('tribulnation.binance.market.spot_market', 'SpotMarket'),
  ('tribulnation.bit2me.market.spot_market', 'SpotMarket'),
  ('tribulnation.bitget.market.perp_market', 'PerpMarket'),
  ('tribulnation.bitget.market.spot_market', 'SpotMarket'),
  ('tribulnation.bybit.market.perp_market', 'PerpMarket'),
  ('tribulnation.bybit.market.spot_market', 'SpotMarket'),
  ('tribulnation.coinbase.market.spot_market', 'SpotMarket'),
  ('tribulnation.deribit.market.markets', 'Market'),
  ('tribulnation.dydx.market.market', 'Market'),
  ('tribulnation.hyperliquid.market.perps_market', 'PerpMarket'),
  ('tribulnation.hyperliquid.market.spot_market', 'SpotMarket'),
  ('tribulnation.kraken.market.perp_market', 'PerpMarket'),
  ('tribulnation.kraken.market.spot_market', 'SpotMarket'),
  ('tribulnation.kucoin.market.markets', 'Market'),
  ('tribulnation.lighter.market.markets', 'LighterPerpMarket'),
  ('tribulnation.lighter.market.markets', 'LighterSpotMarket'),
  ('tribulnation.mexc.market.perp_market', 'PerpMarket'),
  ('tribulnation.mexc.market.spot_market', 'SpotMarket'),
]


@pytest.mark.parametrize(('module', 'name'), VENUE_MARKETS)
def test_every_venue_accepts_trades_stream_settings(module: str, name: str):
  """Every venue market takes `settings` (empty by default) and so accepts, and ignores,
  other venues' keys."""
  try:
    cls = getattr(import_module(module), name)
  except ImportError:
    pytest.skip(f'{module} is not installed')
  parameter = inspect.signature(cls.trades_stream).parameters['settings']
  assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
  assert parameter.default == {}
