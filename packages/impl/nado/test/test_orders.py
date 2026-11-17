"""Order mapping, placement errors, batches, replacement, cancellation and lookups."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from typing_extensions import Any
from typed_core.exceptions import BadRequest as ClientBadRequest

from tribulnation.nado.core import Shared
from tribulnation.nado.market.markets import NadoPerpMarket, NadoSpotMarket
from tribulnation.nado.market.orders import nado_order
from tribulnation.sdk import AuthError, BadRequest, OrderNotFound, OrderRejected

from .conftest import SENDER, X18, Fake, shared_of

DIGEST = '0x' + 'ab' * 32
OFF_TICK: tuple[Any, ...] = (
  2000,
  'Invalid order price',
  {'status': 'failure', 'error_code': 2000},
)


def btc(shared: Shared) -> NadoPerpMarket:
  """BTC-PERP over `shared`."""
  return NadoPerpMarket(shared=shared, symbol='BTC-PERP', product_id=2)


def kbtc(shared: Shared) -> NadoSpotMarket:
  """KBTC over `shared`."""
  return NadoSpotMarket(shared=shared, symbol='KBTC', product_id=1)


def resting(**changes: Any) -> Any:
  """A resting BTC-PERP buy as `subaccount_orders`/`order` send it."""
  return {
    'product_id': 2,
    'sender': SENDER,
    'price_x18': 32105 * X18,
    'amount': 3_150_000_000_000_000,
    'expiration': 4102444800,
    'nonce': 1,
    'unfilled_amount': 1_150_000_000_000_000,
    'digest': DIGEST,
    'placed_at': datetime(2026, 11, 17, tzinfo=timezone.utc),
    'appendix': 1537,
    'order_type': 'post_only',
    **changes,
  }


@pytest.mark.parametrize(
  'kind,appendix', [('LIMIT', 1), ('POST_ONLY', 1537), ('MARKET', 1 | 1 << 9)]
)
def test_orders_are_limits_with_the_type_in_the_appendix(kind: Any, appendix: int):
  """Every order is a limit at `price`: `MARKET` is IOC; all expire in 2100."""
  o = nado_order({'type': kind, 'qty': '-0.00315', 'price': '32105'})
  assert o == {
    'priceX18': 32105 * X18,
    'amount': -3_150_000_000_000_000,
    'expiration': datetime(2100, 1, 1, tzinfo=timezone.utc),
    'appendix': appendix,
  }


def test_orders_refuse_zero_quantities_and_bad_prices():
  """Nothing is signed for a zero quantity or a non-positive price."""
  with pytest.raises(ValueError):
    nado_order({'type': 'LIMIT', 'qty': 0, 'price': 1})
  with pytest.raises(ValueError):
    nado_order({'type': 'LIMIT', 'qty': 1, 'price': 0})


async def test_place_order_sends_the_client_id_and_returns_the_digest(
  shared: Shared, fake: Any
):
  """The digest is the id; a client id goes out as the integer `id`; perpetual orders
  send no `spot_leverage`."""
  sent: list[dict[str, Any]] = []

  async def place_order(**request: Any) -> Any:
    sent.append(request)
    return {'digest': DIGEST, 'id': 7}

  fake.gateway.place_order = place_order
  r = await btc(shared).place_order(
    {'type': 'POST_ONLY', 'qty': '0.00315', 'price': '32105', 'client_order_id': '7'}
  )
  assert r.id == DIGEST and r.filled_qty is None
  assert sent[0]['product_id'] == 2 and sent[0]['id'] == 7
  assert 'spot_leverage' not in sent[0]


async def test_spot_orders_never_borrow_unless_asked(shared: Shared, fake: Any):
  """Spot orders send `spot_leverage=False`, or the setting's value."""
  sent: list[dict[str, Any]] = []

  async def place_order(**request: Any) -> Any:
    sent.append(request)
    return {'digest': DIGEST}

  fake.gateway.place_order = place_order
  o: Any = {'type': 'POST_ONLY', 'qty': '0.00315', 'price': '32105'}
  await kbtc(shared).place_order(o)
  await kbtc(shared).place_order(o, settings={'nado': {'spot_leverage': True}})
  assert [r['spot_leverage'] for r in sent] == [False, True]


@pytest.mark.parametrize('raw', ['abc', '-1', str(2**64)])
async def test_client_ids_must_be_unsigned_64_bit_integers(shared: Shared, raw: str):
  """A client id the venue cannot take is refused before signing."""
  with pytest.raises(ValueError):
    await btc(shared).place_order(
      {'type': 'LIMIT', 'qty': 1, 'price': 1, 'client_order_id': raw}
    )


async def test_coded_refusals_are_order_rejected(shared: Shared, fake: Any):
  """A placement the sequencer answers with an error code never rested."""

  async def place_order(**request: Any) -> Any:
    raise ClientBadRequest(*OFF_TICK)

  fake.gateway.place_order = place_order
  with pytest.raises(OrderRejected) as info:
    await btc(shared).place_order({'type': 'LIMIT', 'qty': 1, 'price': '1.5'})
  assert info.value.args[0] == 2000


async def test_orders_need_the_key():
  """An address alone reads; it cannot sign."""
  shared = shared_of(Fake(signer=False))
  with pytest.raises(AuthError):
    await btc(shared).place_order({'type': 'LIMIT', 'qty': 1, 'price': 1})
  with pytest.raises(AuthError):
    await btc(shared).cancel_order(DIGEST)


async def test_place_orders_maps_each_result(shared: Shared, fake: Any):
  """Placed orders are responses, refused ones `OrderRejected`, unbuildable ones their
  `ValueError` (and never sent)."""
  sent: list[Any] = []

  async def place_orders(requests: list[Any]) -> Any:
    sent.extend(requests)
    return [{'digest': DIGEST, 'error': None}, {'digest': None, 'error': 'unhealthy'}]

  fake.gateway.place_orders = place_orders
  out = await btc(shared).place_orders(
    [
      {'type': 'LIMIT', 'qty': 1, 'price': 1},
      {'type': 'LIMIT', 'qty': 0, 'price': 1},
      {'type': 'LIMIT', 'qty': 2, 'price': 1},
    ]
  )
  assert len(sent) == 2
  assert getattr(out[0], 'id') == DIGEST
  assert isinstance(out[1], ValueError)
  assert isinstance(out[2], OrderRejected)


async def test_a_refused_batch_refuses_every_order(shared: Shared, fake: Any):
  """The venue validates the batch whole: one coded refusal refuses all."""

  async def place_orders(requests: list[Any]) -> Any:
    raise ClientBadRequest(*OFF_TICK)

  fake.gateway.place_orders = place_orders
  out = await btc(shared).place_orders(
    [{'type': 'LIMIT', 'qty': 1, 'price': 1}, {'type': 'LIMIT', 'qty': 1, 'price': 1}]
  )
  assert all(isinstance(r, OrderRejected) for r in out)


async def test_a_refused_replacement_is_not_order_rejected(shared: Shared, fake: Any):
  """`cancel_and_place` is atomic: the original still rests, so the refusal stays a
  `BadRequest`."""

  async def cancel_and_place(cancel: Any, *, place_order: Any) -> Any:
    assert cancel == {'productIds': [2], 'digests': [DIGEST]}
    raise ClientBadRequest(*OFF_TICK)

  fake.gateway.cancel_and_place = cancel_and_place
  with pytest.raises(BadRequest) as info:
    await btc(shared).replace_order(DIGEST, {'type': 'LIMIT', 'qty': 1, 'price': 1})
  assert not isinstance(info.value, OrderRejected)


async def test_cancelling_a_gone_order_is_order_not_found(shared: Shared, fake: Any):
  """The venue answers with an empty `cancelled_orders`."""
  replies: list[Any] = [{'cancelled_orders': [resting()]}, {'cancelled_orders': []}]

  async def cancel_orders(tx: Any) -> Any:
    assert tx == {'productIds': [2], 'digests': [DIGEST]}
    return replies.pop(0)

  fake.gateway.cancel_orders = cancel_orders
  await btc(shared).cancel_order(DIGEST)
  with pytest.raises(OrderNotFound):
    await btc(shared).cancel_order(DIGEST)


async def test_open_orders_parse_fills_from_the_unfilled_amount(
  shared: Shared, fake: Any
):
  """`filled_qty` is the amount less what is still unfilled."""

  async def subaccount_orders(sender: str, *, product_id: int) -> Any:
    assert (sender, product_id) == (SENDER, 2)
    return {'sender': sender, 'product_id': 2, 'orders': [resting()]}

  fake.gateway.subaccount_orders = subaccount_orders
  [o] = await btc(shared).open_orders()
  assert (o.id, o.price, o.qty, o.filled_qty, o.active) == (
    DIGEST,
    Decimal(32105),
    Decimal('0.00315'),
    Decimal('0.002'),
    True,
  )


async def test_query_order_falls_back_to_the_archive(shared: Shared, fake: Any):
  """Off the book (`2020`), an order that filled is in the archive; one that never
  filled is `None`."""
  archived: list[Any] = [
    {
      'digest': DIGEST,
      'subaccount': SENDER,
      'product_id': 2,
      'amount': 3_150_000_000_000_000,
      'price_x18': 32105 * X18,
      'base_filled': 3_150_000_000_000_000,
    }
  ]

  async def order(product_id: int, *, digest: str) -> Any:
    raise ClientBadRequest(2020, 'not found', {})

  async def orders(*, digests: list[str]) -> Any:
    return {'orders': archived}

  fake.gateway.order = order
  fake.archive.orders = orders
  o = await btc(shared).query_order(DIGEST)
  assert o is not None and not o.active and o.filled_qty == Decimal('0.00315')
  archived.clear()
  assert await btc(shared).query_order(DIGEST) is None


def test_reduce_only_sets_the_appendix_bit():
  """`{'nado': {'reduce_only': True}}` sets bit 11 of the appendix."""
  o = nado_order(
    {'type': 'MARKET', 'qty': '-0.00155', 'price': '60000'},
    {'nado': {'reduce_only': True}},
  )
  assert o['appendix'] == 1 | 1 << 9 | 1 << 11
