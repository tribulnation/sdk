"""Order mapping, placement errors, lookups, cancellations and the fills stream."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from typing_extensions import Any, AsyncIterator
from typed_core.exceptions import (
  ApiError as ClientApiError,
  AuthError as ClientAuthError,
  BadRequest as ClientBadRequest,
)
from typed_core.util import Stream

from tribulnation.grvt.core import CLIENT_ORDER_IDS, Shared
from tribulnation.grvt.market.markets import GrvtPerpMarket
from tribulnation.grvt.market.orders import new_order
from tribulnation.sdk import ApiError, AuthError, BadRequest, OrderRejected
from tribulnation.sdk.market import Trade

BTC = 'BTC_USDT_Perp'
ID = '9759235347865617030'


def market(shared: Shared) -> GrvtPerpMarket:
  """BTC over `shared`."""
  return GrvtPerpMarket(shared=shared, instrument=BTC)


def order(
  status: str, *, buy: bool = True, traded: str = '0', limit: bool = True
) -> Any:
  """A single-leg BTC order as `order`/`open_orders` send it."""
  leg: dict[str, Any] = {
    'instrument': BTC,
    'size': Decimal('0.002'),
    'is_buying_asset': buy,
  }
  if limit:
    leg['limit_price'] = Decimal('49100.0')
  return {
    'order_id': '0x0101',
    'sub_account_id': '1',
    'time_in_force': 'GOOD_TILL_TIME',
    'legs': [leg],
    'metadata': {'client_order_id': ID},
    'state': {
      'status': status,
      'reject_reason': 'UNSPECIFIED',
      'book_size': [Decimal('0.002')],
      'traded_size': [Decimal(traded)],
      'update_time': datetime(2026, 10, 22, tzinfo=timezone.utc),
      'avg_fill_price': [Decimal(0)],
    },
  }


def test_market_orders_send_no_price():
  """`MARKET` is the venue's market order, immediate-or-cancel: a limit price is
  refused (`2020`), so the SDK `price` is not sent."""
  new = new_order(BTC, {'type': 'MARKET', 'qty': -0.002, 'price': 81000}, ID)
  assert new == {
    'is_market': True,
    'time_in_force': 'IMMEDIATE_OR_CANCEL',
    'metadata': {'client_order_id': ID},
    'legs': [{'instrument': BTC, 'size': Decimal('0.002'), 'is_buying_asset': False}],
  }


@pytest.mark.parametrize('kind,post_only', [('LIMIT', False), ('POST_ONLY', True)])
def test_limit_orders_rest_good_till_time(kind: Any, post_only: bool):
  """`LIMIT` and `POST_ONLY` are good-till-time, the latter post-only."""
  new = new_order(BTC, {'type': kind, 'qty': '0.002', 'price': '49100.0'}, ID)
  assert new == {
    'time_in_force': 'GOOD_TILL_TIME',
    'post_only': post_only,
    'metadata': {'client_order_id': ID},
    'legs': [
      {
        'instrument': BTC,
        'size': Decimal('0.002'),
        'limit_price': Decimal('49100.0'),
        'is_buying_asset': True,
      }
    ],
  }


@pytest.mark.parametrize(
  'bad', [{'qty': 0, 'price': 1}, {'qty': 'NaN', 'price': 1}, {'qty': 1, 'price': 0}]
)
def test_invalid_orders_raise_before_signing(bad: dict[str, Any]):
  """A zero or non-finite quantity, or a non-positive limit price."""
  with pytest.raises(ValueError):
    new_order(BTC, {'type': 'LIMIT', **bad}, ID)  # type: ignore[typeddict-item]


async def test_place_order_sends_the_client_order_id(shared: Shared, fake: Any):
  """The caller's id is sent unchanged; without one, a fresh id in `[2^63, 2^64)`. The
  reply is the order as accepted, with nothing reported as filled."""
  sent: list[Any] = []

  async def create_order(new: Any) -> Any:
    """Accept, pending, with the placeholder venue id."""
    sent.append(new)
    return {**order('PENDING'), 'order_id': '0x00'}

  fake.trading.create_order = create_order
  btc = market(shared)
  placed = await btc.place_order(
    {'type': 'POST_ONLY', 'qty': '0.002', 'price': '49100', 'client_order_id': ID}
  )
  assert placed.id == ID and placed.filled_qty is None
  generated = await btc.place_order({'type': 'LIMIT', 'qty': 1, 'price': 2})
  low, high = CLIENT_ORDER_IDS
  assert low <= int(generated.id) < high
  assert [s['metadata']['client_order_id'] for s in sent] == [ID, generated.id]
  assert low <= int(btc.random_client_order_id()) < high


@pytest.mark.parametrize(
  'error',
  [
    ClientBadRequest(2064, 'Invalid limit price tick', {'code': 2064, 'status': 400}),
    ClientBadRequest(2065, 'Order size too granular', {'code': 2065, 'status': 400}),
    ClientBadRequest(
      2066, 'Order below minimum notional', {'code': 2066, 'status': 400}
    ),
    ClientBadRequest(2090, 'Max open orders exceeded', {'code': 2090, 'status': 429}),
  ],
)
async def test_validation_refusals_are_order_rejected(
  shared: Shared, fake: Any, error: Exception
):
  """A coded `4XX` refusal of `create_order` means no order exists (ADR 0043)."""

  async def create_order(new: Any) -> Any:
    """Refuse synchronously."""
    raise error

  fake.trading.create_order = create_order
  with pytest.raises(OrderRejected) as caught:
    await market(shared).place_order({'type': 'LIMIT', 'qty': 1, 'price': 2})
  assert caught.value.args == error.args


@pytest.mark.parametrize(
  'error,expected',
  [
    # The id may belong to the caller's own earlier attempt, accepted.
    (
      ClientBadRequest(
        2012, 'Client Order ID overlaps with existing active order', {'code': 2012}
      ),
      BadRequest,
    ),
    # A non-JSON error: no venue code says the order was refused.
    (ClientBadRequest(400, 'Bad Request'), BadRequest),
    # A client-side check: the venue never answered.
    (ClientBadRequest('A pinned nonce is not a uint32'), BadRequest),
    (ClientApiError(503, 'upstream connect error'), ApiError),
    (ClientAuthError(2001, 'Signature has expired', {'code': 2001}), AuthError),
  ],
)
async def test_ambiguous_failures_are_not_order_rejected(
  shared: Shared, fake: Any, error: Exception, expected: type[Exception]
):
  """Only a definitive venue refusal is `OrderRejected`."""

  async def create_order(new: Any) -> Any:
    """Fail."""
    raise error

  fake.trading.create_order = create_order
  with pytest.raises(expected) as caught:
    await market(shared).place_order({'type': 'LIMIT', 'qty': 1, 'price': 2})
  assert not isinstance(caught.value, OrderRejected)


async def test_placing_needs_the_private_key(make_fake: Any, make_shared: Any):
  """An API key alone reads and cancels; placing raises before any request."""
  fake = make_fake(private_key=False)
  cancelled: list[Any] = []

  async def cancel_order(request: Any) -> Any:
    """Acknowledge."""
    cancelled.append(request)
    return {'ack': True}

  fake.trading.cancel_order = cancel_order
  btc = market(make_shared(fake))
  with pytest.raises(AuthError):
    await btc.place_order({'type': 'MARKET', 'qty': 1, 'price': 1})
  assert await btc.cancel_order(ID) == {'ack': True}
  assert cancelled == [{'client_order_id': ID}]


async def test_query_order_by_client_id(shared: Shared, fake: Any):
  """Found by client order id, signed and with its filled part; unknown ids (`1004`)
  and orders on other instruments are `None`."""
  replies: list[Any] = [
    order('FILLED', buy=False, traded='0.002', limit=False),
    ClientBadRequest(1004, 'Data Not Found', {'code': 1004}),
    {
      **order('OPEN'),
      'legs': [{**order('OPEN')['legs'][0], 'instrument': 'ETH_USDT_Perp'}],
    },
  ]
  requests: list[Any] = []

  async def lookup(request: Any) -> Any:
    """Serve the next reply."""
    requests.append(request)
    reply = replies.pop(0)
    if isinstance(reply, Exception):
      raise reply
    return reply

  fake.trading.order = lookup
  btc = market(shared)
  state = await btc.query_order(ID)
  assert state is not None
  assert (state.id, state.price, state.qty, state.filled_qty, state.active) == (
    ID,
    0,
    Decimal('-0.002'),
    Decimal('-0.002'),
    False,
  )
  assert await btc.query_order('1') is None
  assert await btc.query_order(ID) is None
  assert requests[0] == {'client_order_id': ID}


async def test_open_orders_are_scoped_to_the_market(shared: Shared, fake: Any):
  """Filtered by kind, base and quote; pending and resting orders are active."""
  requests: list[dict[str, Any]] = []

  async def open_orders(**kwargs: Any) -> list[Any]:
    """One resting and one pending order."""
    requests.append(kwargs)
    return [order('OPEN'), order('PENDING')]

  fake.trading.open_orders = open_orders
  states = await market(shared).open_orders()
  assert [(s.qty, s.active) for s in states] == [(Decimal('0.002'), True)] * 2
  assert requests == [{'kind': ['PERPETUAL'], 'base': ['BTC'], 'quote': ['USDT']}]


async def test_cancellations(shared: Shared, fake: Any):
  """Bulk cancels go 100 ids per request; cancel-all is scoped to the market."""
  batches: list[Any] = []
  scoped: list[dict[str, Any]] = []

  async def bulk_orders(batch: Any) -> Any:
    """Acknowledge."""
    batches.append(batch)
    return {'cancel_acks': len(batch['client_order_i_ds'])}

  async def cancel_all_orders(**kwargs: Any) -> Any:
    """Acknowledge."""
    scoped.append(kwargs)
    return {'ack': True}

  fake.trading.bulk_orders = bulk_orders
  fake.trading.cancel_all_orders = cancel_all_orders
  btc = market(shared)
  ids = [str(2**63 + i) for i in range(150)]
  acks = await btc.cancel_orders(ids)
  assert [len(b['client_order_i_ds']) for b in batches] == [100, 50]
  assert acks == [{'cancel_acks': 100}, {'cancel_acks': 50}]
  assert await btc.cancel_open_orders() == {'ack': True}
  assert scoped == [{'kind': ['PERPETUAL'], 'base': ['BTC'], 'quote': ['USDT']}]


async def test_trades_stream_maps_pushed_fills(shared: Shared, fake: Any):
  """`v1.fill` pushes the history's `Fill`; one upstream per instrument."""
  subscribed: list[Any] = []
  unsubscribed: list[bool] = []
  pushed: dict[str, Any] = {
    'event_time': datetime(2026, 10, 22, 8, 59, 10, 242734, tzinfo=timezone.utc),
    'instrument': BTC,
    'is_buyer': False,
    'is_taker': True,
    'size': Decimal('0.002'),
    'price': Decimal('81848.0'),
    'fee': Decimal('0.073663'),
    'fee_currency': 'USDT',
    'trade_id': '305282446-1',
    'client_order_id': ID,
  }

  async def fills() -> AsyncIterator[Any]:
    """One fill."""
    yield pushed

  async def unsubscribe():
    """Record the unsubscription."""
    unsubscribed.append(True)

  async def subscribe(**kwargs: Any) -> Stream[Any, Any, Any]:
    """Subscribe by instrument."""
    subscribed.append(kwargs)
    return Stream(reply={}, stream=fills(), unsubscribe=unsubscribe)

  fake.trading_streams.fills = subscribe
  async with market(shared).trades_stream() as trades:
    trade = await anext(aiter(trades))
  assert trade == Trade(
    id='305282446-1',
    order_id=ID,
    client_order_id=ID,
    price=Decimal('81848.0'),
    qty=Decimal('-0.002'),
    time=pushed['event_time'],
    maker=False,
    fee=Trade.Fee(amount=Decimal('0.073663'), asset='USDT'),
    details=pushed,
  )
  assert subscribed == [{'instrument': BTC}] and unsubscribed == [True]
