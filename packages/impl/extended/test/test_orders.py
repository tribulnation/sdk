"""Order requests built from SDK orders, refusals, cancellation and lookup."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re

from typing_extensions import Any, cast

import pytest
from typed_extended import Extended
from typed_extended.core.envelope import raise_error
from typed_extended.core.exc import Error as ClientError
from typed_extended.info.markets import Market as MarketRow

from tribulnation.extended.core import Shared
from tribulnation.extended.market import orders
from tribulnation.sdk.core import ApiError, AuthError, BadRequest, OrderRejected
from tribulnation.sdk.market import Order

ETH = 'ETH-USD'
RFQ = 'OP-USD'


def market(name: str, *, rfq: bool = False) -> MarketRow:
  """A perpetual's cached row: what order building reads."""
  row: dict[str, Any] = {
    'name': name,
    'type': 'PERPETUAL',
    'status': 'ACTIVE',
    'isRfq': rfq,
    'collateralAssetName': 'USD',
    'tradingConfig': {
      'minPriceChange': Decimal('0.1'),
      'minOrderSizeChange': Decimal('0.001'),
    },
  }
  return cast(MarketRow, row)


def venue_error(status: int, code: int | None) -> ClientError:
  """The exception `typed_extended` raises for an error response."""
  error: dict[str, Any] | None = (
    None if code is None else {'code': code, 'message': 'refused'}
  )
  payload: Any = {'status': 'ERROR', 'error': error} if error else ''
  try:
    raise_error(status, error, payload)
  except ClientError as e:
    return e
  raise AssertionError('raise_error did not raise')


@dataclass
class Orders:
  """Record order requests instead of signing and sending them."""

  calls: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])
  error: Exception | None = None

  async def create(self, request: dict[str, Any]) -> dict[str, Any]:
    """Record an order-book order."""
    return self.answer('create', request)

  async def create_rfq(self, request: dict[str, Any]) -> dict[str, Any]:
    """Record an RFQ order."""
    return self.answer('create_rfq', request)

  def answer(self, endpoint: str, request: dict[str, Any]) -> dict[str, Any]:
    """Record, then fail or accept."""
    self.calls.append((endpoint, dict(request)))
    if self.error is not None:
      raise self.error
    return {'id': 2112522693715927040, 'externalId': request.get('id', 'hash')}

  async def cancel(self, id: int) -> None:
    """Record a cancel."""
    self.calls.append(('cancel', id))

  async def mass_cancel(self, order_ids: list[int] | None = None) -> None:
    """Record a mass cancel."""
    self.calls.append(('mass_cancel', order_ids))


@dataclass
class Account:
  """Serve open orders and one order lookup."""

  open: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
  found: dict[str, Any] | None = None
  queries: list[Any] = field(default_factory=list[Any])

  async def open_orders(self, market: list[str], *, type: str) -> list[dict[str, Any]]:
    """The fixture's open orders."""
    self.queries.append((market, type))
    return self.open

  async def order(self, id: int) -> dict[str, Any] | None:
    """The fixture's order, if any."""
    self.queries.append(id)
    return self.found


@dataclass
class Network:
  """The deployment name the order expiry reads."""

  name: str = 'mainnet'


@dataclass
class Credentials:
  """Credentials with or without a Stark account."""

  stark: object | None = field(default_factory=object)


@dataclass
class Client:
  """The client attributes the order paths reach."""

  orders: Orders = field(default_factory=Orders)
  account: Account = field(default_factory=Account)
  credentials: Credentials | None = field(default_factory=Credentials)
  network: Network = field(default_factory=Network)


def shared(client: Client) -> Shared:
  """Shared state over the fake client, with ETH and an RFQ market cached."""
  out = Shared(client=cast(Extended, client))
  out.markets.update({ETH: market(ETH), RFQ: market(RFQ, rfq=True)})
  return out


def resting_order(o: dict[str, Any]) -> dict[str, Any]:
  """A venue order row as `account.order` and `open_orders` return it."""
  row: dict[str, Any] = {
    'id': 11,
    'market': ETH,
    'type': 'LIMIT',
    'side': 'SELL',
    'status': 'NEW',
    'price': Decimal('2500'),
    'qty': Decimal('0.5'),
    'filledQty': Decimal('0.1'),
  }
  return {**row, **o}


@pytest.mark.parametrize(
  ('network', 'lifetime'),
  [('mainnet', timedelta(days=90)), ('testnet', timedelta(days=28))],
)
async def test_limit_rests_until_the_network_maximum(network: str, lifetime: timedelta):
  """`LIMIT` is a GTT sell at the absolute size, expiring at the network's longest
  lifetime less a minute, with the caller's client id."""
  client = Client(network=Network(network))
  before = datetime.now(timezone.utc)
  order: Order = {
    'qty': '-0.5',
    'price': '2500.1',
    'type': 'LIMIT',
    'client_order_id': 'ab' * 16,
  }
  response = await orders.place_order(shared(client), market(ETH), order)
  after = datetime.now(timezone.utc)
  ((endpoint, request),) = client.orders.calls
  expiry = request.pop('expiryEpochMillis')
  assert endpoint == 'create'
  assert request == {
    'type': 'LIMIT',
    'market': ETH,
    'side': 'SELL',
    'qty': Decimal('0.5'),
    'price': Decimal('2500.1'),
    'timeInForce': 'GTT',
    'selfTradeProtectionLevel': 'ACCOUNT',
    'postOnly': False,
    'id': 'ab' * 16,
  }
  margin = timedelta(minutes=1)
  assert before + lifetime - margin <= expiry <= after + lifetime - margin
  assert response.id == '2112522693715927040' and response.filled_qty is None


async def test_post_only_and_market_orders():
  """`POST_ONLY` adds `postOnly`; `MARKET` is IOC with the core's default expiry."""
  client = Client()
  await orders.place_order(
    shared(client), market(ETH), {'qty': '1', 'price': '2400', 'type': 'POST_ONLY'}
  )
  await orders.place_order(
    shared(client), market(ETH), {'qty': '1', 'price': '2600', 'type': 'MARKET'}
  )
  (_, post_only), (_, market_order) = client.orders.calls
  assert post_only['postOnly'] is True and post_only['side'] == 'BUY'
  assert 'id' not in post_only
  assert market_order == {
    'type': 'MARKET',
    'market': ETH,
    'side': 'BUY',
    'qty': Decimal('1'),
    'price': Decimal('2600'),
    'timeInForce': 'IOC',
    'selfTradeProtectionLevel': 'ACCOUNT',
  }


@pytest.mark.parametrize('type', ['LIMIT', 'MARKET'])
async def test_rfq_markets_route_through_create_rfq(type: Any):
  """An RFQ market's orders go to the RFQ endpoint, without `postOnly`."""
  client = Client()
  order: Order = {'qty': '-3', 'price': '0.1', 'type': type}
  await orders.place_order(shared(client), market(RFQ, rfq=True), order)
  ((endpoint, request),) = client.orders.calls
  assert endpoint == 'create_rfq'
  assert 'postOnly' not in request
  assert request['timeInForce'] == ('GTT' if type == 'LIMIT' else 'IOC')


@pytest.mark.parametrize(
  ('order', 'rfq', 'message'),
  [
    ({'qty': '1', 'price': '2400.05', 'type': 'LIMIT'}, False, 'tick'),
    ({'qty': '0.0005', 'price': '2400', 'type': 'LIMIT'}, False, 'step'),
    ({'qty': '0', 'price': '2400', 'type': 'LIMIT'}, False, 'non-zero'),
    ({'qty': '1', 'price': '0', 'type': 'MARKET'}, False, 'positive'),
    ({'qty': '1', 'price': '0.1', 'type': 'POST_ONLY'}, True, 'post-only'),
  ],
)
async def test_invalid_orders_raise_before_signing(
  order: Order, rfq: bool, message: str
):
  """Off-grid, empty or unpriced orders, and post-only on RFQ, never reach the venue."""
  client = Client()
  row = market(RFQ if rfq else ETH, rfq=rfq)
  with pytest.raises(ValueError, match=message):
    await orders.place_order(shared(client), row, order)
  assert client.orders.calls == []


async def test_trading_needs_the_stark_key():
  """A client without a Stark account raises `AuthError` before any request."""
  client = Client(credentials=Credentials(stark=None))
  with pytest.raises(AuthError, match='Stark'):
    await orders.place_order(
      shared(client), market(ETH), {'qty': '1', 'price': '2400', 'type': 'LIMIT'}
    )
  assert client.orders.calls == []


@pytest.mark.parametrize(
  ('status', 'code', 'expected'),
  [
    (400, 1140, OrderRejected),
    (422, 1121, OrderRejected),
    (200, 1001, OrderRejected),
    (400, 1134, BadRequest),
    (400, 1006, BadRequest),
    (404, None, BadRequest),
    (500, 1006, ApiError),
    (503, None, ApiError),
  ],
)
async def test_only_coded_refusals_are_rejections(
  status: int, code: int | None, expected: type[Exception]
):
  """A coded refusal is `OrderRejected`; a duplicate client id, the catch-all code, a
  code-less status and a server error stay ambiguous."""
  client = Client(orders=Orders(error=venue_error(status, code)))
  with pytest.raises(expected) as raised:
    await orders.place_order(
      shared(client), market(ETH), {'qty': '1', 'price': '2400', 'type': 'LIMIT'}
    )
  if expected is not OrderRejected:
    assert not isinstance(raised.value, OrderRejected)


def test_random_client_order_ids_are_32_hex_digits():
  """ADR 0029's common form, fresh on every call."""
  first, second = orders.random_client_order_id(), orders.random_client_order_id()
  assert re.fullmatch('[0-9a-f]{32}', first) and first != second


async def test_cancel_open_orders_cancels_what_open_orders_lists():
  """`cancel_open_orders` mass-cancels the listed `LIMIT` orders' ids, and sends nothing
  when none are open."""
  client = Client(account=Account(open=[resting_order({}), resting_order({'id': 12})]))
  await orders.cancel_open_orders(shared(client), ETH)
  assert client.account.queries == [([ETH], 'LIMIT')]
  assert client.orders.calls == [('mass_cancel', [11, 12])]
  empty = Client()
  assert await orders.cancel_open_orders(shared(empty), ETH) is None
  assert empty.orders.calls == []


async def test_cancels_take_numeric_ids():
  """Cancels send Extended's integer ids; a non-numeric id raises before any request."""
  client = Client()
  await orders.cancel_order(shared(client), '2112522693715927040')
  await orders.cancel_orders(shared(client), ['1', '2'])
  assert await orders.cancel_orders(shared(client), []) is None
  assert client.orders.calls == [
    ('cancel', 2112522693715927040),
    ('mass_cancel', [1, 2]),
  ]
  with pytest.raises(ValueError):
    await orders.cancel_order(shared(client), 'abc')


async def test_query_order_parses_signed_quantities():
  """A known order of this market parses with signed sizes; another market's, or an
  unknown id (`None` from the client), is `None`."""
  found = Client(account=Account(found=resting_order({})))
  state = await orders.query_order(shared(found), ETH, '11')
  assert state is not None
  assert (state.id, state.qty, state.filled_qty, state.active) == (
    '11',
    Decimal('-0.5'),
    Decimal('-0.1'),
    True,
  )
  other = Client(account=Account(found=resting_order({'market': 'BTC-USD'})))
  assert await orders.query_order(shared(other), ETH, '11') is None
  assert await orders.query_order(shared(Client()), ETH, '11') is None
