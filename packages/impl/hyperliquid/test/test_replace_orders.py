"""`replace_orders` modifies post-only entries in one `batchModify`, and `cancel_order`
tells a gone order from an ambiguous failure."""

from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, cast
from unittest.mock import AsyncMock

import pytest

from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin
from tribulnation.hyperliquid.market.impl.orders import (
  cancel_order,
  replace_order,
  replace_orders,
)
from tribulnation.sdk.core import ApiError, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse

POST_ONLY: Order = {'qty': Decimal('1'), 'price': Decimal('10'), 'type': 'POST_ONLY'}
LIMIT: Order = {'qty': Decimal('-1'), 'price': Decimal('11'), 'type': 'LIMIT'}
NEVER_PLACED = 'Order was never placed, already canceled, or filled. asset=3'


def ok(*statuses: Any) -> dict[str, Any]:
  """An accepted action carrying the given per-order statuses."""
  return {
    'status': 'ok',
    'response': {'type': 'order', 'data': {'statuses': list(statuses)}},
  }


def market(
  *,
  modify: Any = None,
  order: Any = None,
  cancel: Any = None,
) -> PerpMarketMixin:
  """A market whose client's exchange endpoints are the given mocks."""
  exchange = SimpleNamespace(
    modify_orders=AsyncMock(return_value=modify),
    order=AsyncMock(return_value=order),
    cancel=AsyncMock(return_value=cancel),
  )
  return cast(
    PerpMarketMixin,
    SimpleNamespace(
      asset_id=3, tick_size=Decimal('0.0001'), client=SimpleNamespace(exchange=exchange)
    ),
  )


def endpoint(m: PerpMarketMixin, name: str) -> AsyncMock:
  """The mock behind one of `m`'s exchange endpoints."""
  return getattr(cast(Any, m).client.exchange, name)


async def test_post_only_entries_share_one_modify():
  """Post-only entries go in one `batchModify`, without always-place, each answered
  with its new order ID."""
  m = market(modify=ok({'resting': {'oid': 7}}, {'resting': {'oid': 8}}))

  results = await replace_orders(m, [('1', POST_ONLY), ('2', POST_ONLY)])

  modify = endpoint(m, 'modify_orders')
  (modifies,) = modify.call_args.args
  assert [x['oid'] for x in modifies] == [1, 2]
  assert modify.call_args.kwargs == {}
  assert [r.id for r in results if isinstance(r, OrderResponse)] == ['7', '8']


async def test_gone_entry_is_placed_afresh():
  """Hyperliquid places nothing when the old order is gone, so the entry is placed;
  another entry error is ambiguous."""
  m = market(
    modify=ok({'error': 'Cannot modify canceled or filled order'}, {'error': 'busy'}),
    order=ok({'resting': {'oid': 9}}),
  )

  placed, refused = await replace_orders(m, [('1', POST_ONLY), ('2', POST_ONLY)])

  assert endpoint(m, 'order').await_count == 1
  assert isinstance(placed, OrderResponse) and placed.id == '9'
  assert type(refused) is ApiError


async def test_refused_new_order_is_rejected():
  """The venue cancelled the old order and refused the new one: nothing rests."""
  crossing = (
    'Error placing new order during modify: Post only order would have immediately '
    'matched, bbo was 2244@2244.1.'
  )
  m = market(modify=ok({'error': crossing}))

  (result,) = await replace_orders(m, [('1', POST_ONLY)])

  assert isinstance(result, OrderRejected)
  endpoint(m, 'order').assert_not_awaited()


async def test_other_types_cancel_then_place():
  """An entry `batchModify` can't take without always-place cancels, then places, in
  input order next to the modified ones."""
  m = market(
    modify=ok({'resting': {'oid': 7}}),
    order=ok({'resting': {'oid': 9}}),
    cancel=ok({'error': NEVER_PLACED}),
  )

  limit, post_only = await replace_orders(m, [('1', LIMIT), ('2', POST_ONLY)])

  assert isinstance(limit, OrderResponse) and limit.id == '9'
  assert isinstance(post_only, OrderResponse) and post_only.id == '7'
  ((cancelled,),) = endpoint(m, 'cancel').call_args.kwargs.values()
  assert cancelled == {'a': 3, 'o': 1}


async def test_failed_cancel_places_nothing():
  """A cancel failing for another reason fails the entry without placing."""
  m = market(cancel=ok({'error': 'busy'}))

  (result,) = await replace_orders(m, [('1', LIMIT)])

  assert type(result) is ApiError
  endpoint(m, 'order').assert_not_awaited()


async def test_refused_action_fails_every_modified_entry():
  """A refused action modified nothing: every entry is an ambiguous error."""
  m = market(modify={'status': 'err', 'response': 'rate limited'})

  results = await replace_orders(m, [('1', POST_ONLY), ('2', POST_ONLY)])

  assert [type(r) for r in results] == [ApiError, ApiError]


async def test_replace_order_raises_its_error():
  """A single replace raises what its entry failed with."""
  m = market(modify=ok({'error': 'busy'}))

  with pytest.raises(ApiError, match='busy'):
    await replace_order(m, '1', POST_ONLY)


async def test_cancel_of_a_gone_order_is_not_found():
  """The venue's `never placed` answer is `OrderNotFound`; others stay `ApiError`."""
  with pytest.raises(OrderNotFound):
    await cancel_order(market(cancel=ok({'error': NEVER_PLACED})), '1')
  with pytest.raises(ApiError) as raised:
    await cancel_order(market(cancel=ok({'error': 'busy'})), '1')
  assert not isinstance(raised.value, OrderNotFound)
