"""Order requests built from SDK orders, refusals, cancellation, lookup and open orders."""

from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace

from typing_extensions import Any, cast

import pytest
from typed_risex import RISEx, BadRequest as ClientBadRequest
from typed_risex.markets.all import MarketInfo

from tribulnation.risex.core import CLIENT_ORDER_IDS, Shared, random_client_order_id
from tribulnation.risex.market import orders
from tribulnation.sdk.core import AuthError, BadRequest, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order

ORDER_ID = '0x000000000003b131000000000390d5e400000000000000ec'


def market() -> MarketInfo:
  """BTC/USDC's cached row: what order building reads."""
  row: dict[str, Any] = {
    'market_id': 1,
    'config': {
      'name': 'BTC/USDC',
      'step_size': Decimal('0.000001'),
      'step_price': Decimal('0.1'),
    },
  }
  return cast(MarketInfo, row)


def order_row(**overrides: Any) -> dict[str, Any]:
  """An `orders.get`/`orders.history` row of a resting post-only bid."""
  row: dict[str, Any] = {
    'id': ORDER_ID,
    'market_id': 1,
    'price': Decimal('51082'),
    'size': Decimal('0.0002'),
    'filled_size': Decimal('0.0001'),
    'side': 'BUY',
    'status': 'ORDER_STATUS_OPEN',
  }
  return row | overrides


def refusal(code: str, message: str) -> ClientBadRequest:
  """The exception `typed_risex` raises for a RISEx error envelope."""
  return ClientBadRequest(code, message, {'error': {'code': code, 'message': message}})


@dataclass
class Orders:
  """Record order calls instead of signing and sending them."""

  calls: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])
  error: Exception | None = None
  placed: dict[str, Any] = field(
    default_factory=lambda: {'order_id': ORDER_ID, 'filled_quantity': ''}
  )
  found: dict[str, Any] = field(default_factory=order_row)
  resting: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
  history: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

  async def place(self, request: Any) -> Any:
    """Record a placement."""
    self.calls.append(('place', request))
    if self.error is not None:
      raise self.error
    return self.placed

  async def cancel(self, market_id: int, *, order_id: str) -> Any:
    """Record a cancel."""
    self.calls.append(('cancel', (market_id, order_id)))
    if self.error is not None:
      raise self.error
    return {'success': True}

  async def get(self, order_id: str, *, market_id: int | None = None) -> Any:
    """Look an order up."""
    self.calls.append(('get', order_id))
    if self.error is not None:
      raise self.error
    return {'order': self.found}

  async def open(self, *, account: str, market_id: int | None = None) -> Any:
    """The resting orders."""
    return {'orders': self.resting}

  def history_paged(self, **kwargs: Any) -> Any:
    """One page of indexed open orders."""
    history = self.history

    class Pages:
      """A one-page walk."""

      def via(self, call: Any) -> Any:
        """Iterate without middleware."""

        async def pages():
          yield history

        return pages()

    return Pages()


def shared(fake: Orders, *, signer: bool = True) -> Shared:
  """A `Shared` over a fake client, with or without a signer key."""
  credentials = SimpleNamespace(signer_key=object() if signer else None)
  client = SimpleNamespace(orders=fake, credentials=credentials)
  return Shared(client=cast(RISEx, client), address='0xabc')


def test_mapping_of_each_order_type():
  """`LIMIT` rests, `POST_ONLY` adds `post_only`, `MARKET` is an IOC limit; sizes and
  prices are whole steps and ticks, sells are side 1."""
  limit = orders.order_request(
    market(), {'type': 'LIMIT', 'qty': '0.0001', 'price': '50000'}
  )
  assert limit == {
    'market_id': 1,
    'order_type': 1,
    'side': 0,
    'size_steps': 100,
    'price_ticks': 500000,
  }
  post = orders.order_request(
    market(), {'type': 'POST_ONLY', 'qty': Decimal('-0.0001'), 'price': '50000.1'}
  )
  assert post['side'] == 1 and post.get('post_only') is True
  assert post['price_ticks'] == 500001
  ioc = orders.order_request(
    market(),
    {'type': 'MARKET', 'qty': '0.0001', 'price': '50000', 'client_order_id': '42'},
  )
  assert ioc['order_type'] == 1 and ioc.get('time_in_force') == 3
  assert ioc.get('client_order_id') == 42


@pytest.mark.parametrize(
  'order',
  [
    {'type': 'LIMIT', 'qty': '0.0000001', 'price': '50000'},
    {'type': 'LIMIT', 'qty': '0.0001', 'price': '50000.05'},
    {'type': 'LIMIT', 'qty': '0', 'price': '50000'},
    {'type': 'LIMIT', 'qty': '0.0001', 'price': '0'},
    {'type': 'LIMIT', 'qty': '0.0001', 'price': '50000', 'client_order_id': 'abc'},
  ],
)
def test_invalid_orders_raise_before_signing(order: dict[str, Any]):
  """Off-grid sizes and prices, zero sizes, non-positive prices and non-integer client
  ids raise `ValueError`."""
  with pytest.raises(ValueError):
    orders.order_request(market(), cast(Order, order))


async def test_place_reports_ioc_fills_only():
  """`filled_qty` is the 1e18-scaled `filled_quantity` of an IOC, `None` when `''`."""
  fake = Orders()
  resting = await orders.place_order(
    shared(fake), market(), {'type': 'LIMIT', 'qty': '0.0001', 'price': '50000'}
  )
  assert resting.id == ORDER_ID and resting.filled_qty is None
  fake.placed = {'order_id': ORDER_ID, 'filled_quantity': 100000000000000}
  filled = await orders.place_order(
    shared(fake), market(), {'type': 'MARKET', 'qty': '0.0001', 'price': '50000'}
  )
  assert filled.filled_qty == Decimal('0.0001')


async def test_place_needs_a_signer():
  """Without a signer key nothing is sent."""
  fake = Orders()
  with pytest.raises(AuthError):
    await orders.place_order(
      shared(fake, signer=False),
      market(),
      {'type': 'LIMIT', 'qty': '0.0001', 'price': '50000'},
    )
  assert fake.calls == []


@pytest.mark.parametrize(
  'error',
  [
    refusal('FailedPrecondition', 'PlaceOrder reverted: PostOnlyOrderMatched()'),
    refusal('InvalidArgument', 'invalid size'),
  ],
)
async def test_refusals_raise_order_rejected(error: Exception):
  """A reverted or invalid placement is `OrderRejected`."""
  fake = Orders(error=error)
  with pytest.raises(OrderRejected):
    await orders.place_order(
      shared(fake), market(), {'type': 'POST_ONLY', 'qty': '0.0001', 'price': '50000'}
    )


async def test_other_errors_stay_ambiguous():
  """An internal error may have placed the order: never `OrderRejected`."""
  fake = Orders(error=refusal('Internal', 'boom'))
  with pytest.raises(Exception) as caught:
    await orders.place_order(
      shared(fake), market(), {'type': 'LIMIT', 'qty': '0.0001', 'price': '50000'}
    )
  assert not isinstance(caught.value, OrderRejected)


@pytest.mark.parametrize(
  'message',
  ['order 241969 is not open (status: 3)', 'order is already filled or cancelled'],
)
async def test_cancel_of_a_closed_order_is_not_found(message: str):
  """Cancelling an order no longer resting raises `OrderNotFound`."""
  fake = Orders(error=refusal('InvalidArgument', message))
  with pytest.raises(OrderNotFound):
    await orders.cancel_order(shared(fake), 1, ORDER_ID)


async def test_cancel_other_refusals_propagate():
  """Another invalid-argument refusal is not read as a missing order."""
  fake = Orders(error=refusal('InvalidArgument', 'bad signature'))
  with pytest.raises(BadRequest) as caught:
    await orders.cancel_order(shared(fake), 1, ORDER_ID)
  assert not isinstance(caught.value, OrderNotFound)


async def test_query_order():
  """Sizes are signed by side; an unknown id or another market's order is `None`."""
  fake = Orders()
  state = await orders.query_order(shared(fake), 1, ORDER_ID)
  assert state is not None and state.active
  assert (state.qty, state.filled_qty) == (Decimal('0.0002'), Decimal('0.0001'))
  fake.found = order_row(side='SELL', status='ORDER_STATUS_CANCELLED')
  state = await orders.query_order(shared(fake), 1, ORDER_ID)
  assert state is not None and not state.active and state.qty == Decimal('-0.0002')
  assert await orders.query_order(shared(fake), 2, ORDER_ID) is None
  fake.error = refusal('NotFound', 'order not found')
  assert await orders.query_order(shared(fake), 1, ORDER_ID) is None


async def test_open_orders_take_fills_from_the_index():
  """Resting orders come from `orders.open`, their fill progress from the indexer, else
  from their own lookup."""
  other = '0x' + 'f' * 48
  fake = Orders(
    resting=[
      {'order_id': ORDER_ID, 'market_id': 1},
      {'order_id': other, 'market_id': 1},
    ],
    history=[order_row()],
    found=order_row(id=other, filled_size=Decimal(0)),
  )
  states = await orders.open_orders(shared(fake), 1)
  assert [s.id for s in states] == [ORDER_ID, other]
  assert states[0].filled_qty == Decimal('0.0001')
  assert states[1].filled_qty == Decimal(0)
  assert [c for c in fake.calls if c[0] == 'get'] == [('get', other)]


def test_random_client_order_ids_are_decimal():
  """Generated client ids are decimal integers the venue accepts."""
  ids = {random_client_order_id() for _ in range(20)}
  assert all(i.isdigit() and int(i) < CLIENT_ORDER_IDS for i in ids)
  assert len(ids) > 1
