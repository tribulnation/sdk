"""Client order IDs travel inside `Order` and come back on `Trade`."""

from typing_extensions import Any, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.sdk.market import (
  Exchange,
  ExchangeTrade,
  Market,
  Order,
  OrderResponse,
  Trade,
  TradingMarkets,
  TradingVenue,
)

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeMarket(Market):
  """A market recording the orders it is asked to place."""

  placed: list[Order]

  @property
  def market_id(self) -> str:
    return 'BTCUSDT'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def venue_id(self) -> str:
    return 'fake'

  async def place_order(self, order: Order, *, settings: Any = {}) -> OrderResponse:
    self.placed.append(order)
    return OrderResponse(id=str(len(self.placed)))

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

  def trades_stream(self, **kwargs: Any) -> Any:
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


def fixture() -> tuple[FakeMarket, FakeMarkets]:
  """One market behind an exchange, a venue and a routing root."""
  market = FakeMarket(placed=[])
  return market, FakeMarkets(fake=FakeVenue(fake=FakeExchange(fake=market)))


def test_trade_ids_default_to_unknown():
  """Existing constructors keep working; venues that report nothing leave `None`."""
  trade = Trade(id='1', price=Decimal('2'), qty=Decimal('1'), time=T0, maker=True)
  assert trade.order_id is None
  assert trade.client_order_id is None


def test_exchange_trade_copies_order_ids():
  """An exchange-wide row built from a market row keeps both order IDs."""
  trade = Trade(
    id='1',
    order_id='42',
    client_order_id='hedge-1',
    price=Decimal('2'),
    qty=Decimal('-1'),
    time=T0,
    maker=False,
  )
  row = ExchangeTrade(**vars(trade), market_id='BTCUSDT')
  assert (row.order_id, row.client_order_id) == ('42', 'hedge-1')


async def test_routing_forwards_client_order_ids_unchanged():
  """`place_order` and `place_orders` hand each order to the market as given."""
  market, root = fixture()
  order: Order = {'type': 'LIMIT', 'qty': 1, 'price': 2, 'client_order_id': 'a'}
  await root.place_order('fake:spot:BTCUSDT', order)
  await root.place_orders(
    'fake:spot:BTCUSDT',
    [
      {'type': 'LIMIT', 'qty': 1, 'price': 2, 'client_order_id': 'b'},
      {'type': 'LIMIT', 'qty': -1, 'price': 3},
    ],
  )
  assert [o.get('client_order_id') for o in market.placed] == ['a', 'b', None]
  assert market.placed[0] is order


def test_markets_default_to_ignoring_client_order_ids():
  """A market that does not override the generator ignores client order IDs."""
  market, _ = fixture()
  assert market.random_client_order_id() is None


async def test_generated_id_goes_into_the_order_unchecked():
  """A `None` from the generator is a valid `client_order_id`, reaching the market as given."""
  market, _ = fixture()
  await market.place_order(
    {
      'type': 'LIMIT',
      'qty': 1,
      'price': 2,
      'client_order_id': market.random_client_order_id(),
    }
  )
  assert market.placed[0].get('client_order_id') is None
