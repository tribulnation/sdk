"""Client order IDs travel inside `Order` and come back on `Trade`."""

from typing_extensions import Any, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import re

import pytest

from tribulnation.sdk.market import (
  ClientOrderIdFormat,
  Exchange,
  ExchangeTrade,
  Market,
  Order,
  OrderResponse,
  Rules,
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

  async def depth(self, *, levels: int | None = None) -> Any:
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


def rules(client_order_id_format: ClientOrderIdFormat | None) -> Rules:
  """Minimal rules in the given client order ID format."""
  return Rules(
    fee_asset='USDT',
    tick_size=Decimal('0.01'),
    step_size=Decimal('0.001'),
    api=True,
    client_order_id_format=client_order_id_format,
  )


@pytest.mark.parametrize(
  'client_order_id_format,pattern',
  [
    ('hex', r'[0-9a-f]{32}'),
    ('0x-hex', r'0x[0-9a-f]{32}'),
    (None, r'[0-9a-f]{32}'),
  ],
)
def test_random_client_id_follows_the_market_format(
  client_order_id_format: ClientOrderIdFormat | None, pattern: str
):
  """Each ID carries 128 fresh random bits in the market's format."""
  market = rules(client_order_id_format)
  ids = {market.random_client_id() for _ in range(100)}
  assert len(ids) == 100
  assert all(re.fullmatch(pattern, value) for value in ids)


def test_rules_default_to_ignoring_client_order_ids():
  """Rules that do not state a format describe a market ignoring the IDs."""
  market = Rules(fee_asset='USDT', tick_size=Decimal(1), step_size=Decimal(1), api=True)
  assert market.client_order_id_format is None
