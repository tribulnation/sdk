"""`Settings.fast_cancel` sends `f: true` on every cancel, signed into the action, and
raises a refusal rather than resending it; disabled, the flag is omitted. Each test signs with a throwaway key and answers
from a stub transport: nothing reaches the network."""

import copy
from collections.abc import Callable, Iterator
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from eth_account import Account
from typing_extensions import Any, cast
from typed_hyperliquid import Hyperliquid
from typed_hyperliquid.exchange import Exchange
import typed_hyperliquid.exchange.core as exchange_core

from tribulnation.hyperliquid.market.impl.mixin import PerpMeta, Shared
from tribulnation.hyperliquid.market.perps_market import PerpMarket
from tribulnation.sdk.core import ApiError, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, Settings

ADDRESS = '0x' + '1' * 40
FAST: Settings = {'hyperliquid': {'fast_cancel': True}}
LIMIT: Order = {'qty': Decimal('1'), 'price': Decimal('10'), 'type': 'LIMIT'}
SUCCESS: dict[str, Any] = {
  'status': 'ok',
  'response': {'type': 'cancel', 'data': {'statuses': ['success']}},
}
NEVER_PLACED = 'Order was never placed, already canceled, or filled. asset=3'
TRIGGER_REFUSAL = 'Cannot fast cancel a trigger order.'
"""Stand-in for Hyperliquid's refusal of a fast cancel naming a trigger order: its text is
undocumented, and the SDK does not depend on it."""


def entry(stat: Any) -> dict[str, Any]:
  """An accepted cancel action with one entry status."""
  return {'status': 'ok', 'response': {'type': 'cancel', 'data': {'statuses': [stat]}}}


class Venue:
  """A real `Exchange` client over a stub transport.

  `signed` collects every action as the signer received it (see the `signed` fixture);
  `posted` every body the transport was asked to send. Cancels are answered from
  `cancels` in order, orders with one resting status.
  """

  def __init__(self, signed: list[dict[str, Any]], *cancels: dict[str, Any]):
    self.exchange = Exchange.http(Account.create().key.hex(), mainnet=False)
    self.signed = signed
    self.cancels = list(cancels)
    self.posted: list[dict[str, Any]] = []
    cast(Any, self.exchange.client).request = AsyncMock(side_effect=self.answer)

  async def answer(self, body: dict[str, Any]) -> dict[str, Any]:
    """The stub transport's reply to one signed envelope."""
    self.posted.append(copy.deepcopy(body))
    if body['action']['type'] == 'cancel':
      return self.cancels.pop(0)
    else:
      return {
        'status': 'ok',
        'response': {'type': 'order', 'data': {'statuses': [{'resting': {'oid': 9}}]}},
      }

  def cancel_actions(self) -> list[dict[str, Any]]:
    """The signed cancel actions, each checked to be what was posted."""
    assert self.signed == [body['action'] for body in self.posted]
    return [a for a in self.signed if a['type'] == 'cancel']


@pytest.fixture
def signed() -> Iterator[list[dict[str, Any]]]:
  """Every action the exchange core signs, recorded at the signing boundary and then
  signed for real."""
  actions: list[dict[str, Any]] = []
  real = exchange_core.sign_l1_action

  def sign(action: dict[str, Any], **kwargs: Any) -> Any:
    actions.append(copy.deepcopy(action))
    return real(action, **kwargs)

  with patch.object(exchange_core, 'sign_l1_action', sign):
    yield actions


@pytest.fixture
def venue(signed: list[dict[str, Any]]) -> Callable[..., Venue]:
  """Build a `Venue` recording into `signed`, answering cancels with the given replies."""
  return lambda *cancels: Venue(signed, *cancels)


def market(v: Venue, *, open_orders: list[dict[str, Any]] = []) -> PerpMarket:
  """A perpetual (asset 3) trading through `v`, with the given frontend open orders."""
  asset: dict[str, Any] = {
    'name': 'SAGA',
    'maxLeverage': 10,
    'szDecimals': 1,
    'marginTableId': 10,
  }
  info = SimpleNamespace(frontend_open_orders=AsyncMock(return_value=open_orders))
  client = cast(Hyperliquid, SimpleNamespace(info=info, exchange=v.exchange))
  meta = cast(
    PerpMeta, {'asset_idx': 3, 'asset_meta': asset, 'collateral_meta': {'index': 0}}
  )
  return PerpMarket(
    shared=Shared(client=client, maybe_address=ADDRESS), dex=None, meta=meta
  )


def frontend(oid: int, *, trigger: bool) -> dict[str, Any]:
  """A `frontendOpenOrders` row of SAGA."""
  return {
    'coin': 'SAGA',
    'oid': oid,
    'origSz': '1',
    'sz': '1',
    'limitPx': '10',
    'isTrigger': trigger,
  }


async def test_disabled_omits_the_flag(venue: Callable[..., Venue]):
  """Without the setting, the signed action carries no `f`."""
  v = venue(SUCCESS)
  assert await market(v).cancel_order('5') == 'success'
  assert v.cancel_actions() == [{'type': 'cancel', 'cancels': [{'a': 3, 'o': 5}]}]


async def test_explicit_false_omits_the_flag(venue: Callable[..., Venue]):
  """`fast_cancel: False` is the default, not `f: false`."""
  v = venue(SUCCESS)
  await market(v).cancel_order('5', settings={'hyperliquid': {'fast_cancel': False}})
  assert 'f' not in v.cancel_actions()[0]


async def test_enabled_signs_the_flag(venue: Callable[..., Venue]):
  """The flag is in the action before it is signed, and sent as signed."""
  v = venue(SUCCESS)
  assert await market(v).cancel_order('5', settings=FAST) == 'success'
  assert v.cancel_actions() == [
    {'type': 'cancel', 'cancels': [{'a': 3, 'o': 5}], 'f': True}
  ]


@pytest.mark.parametrize(
  'refusal',
  [entry({'error': TRIGGER_REFUSAL}), {'status': 'err', 'response': TRIGGER_REFUSAL}],
)
async def test_refused_fast_cancel_is_raised(
  venue: Callable[..., Venue], refusal: dict[str, Any]
):
  """A trigger order refuses the fast path (as an entry or the whole action): the refusal
  is raised as `ApiError`, not `OrderNotFound` or `OrderRejected`, and nothing is resent."""
  v = venue(refusal)
  with pytest.raises(ApiError) as raised:
    await market(v).cancel_order('5', settings=FAST)
  assert not isinstance(raised.value, (OrderNotFound, OrderRejected))
  assert v.cancel_actions() == [
    {'type': 'cancel', 'cancels': [{'a': 3, 'o': 5}], 'f': True}
  ]


async def test_gone_order_is_order_not_found(venue: Callable[..., Venue]):
  """A fast cancel of an order that no longer rests is `OrderNotFound`, sent once."""
  v = venue(entry({'error': NEVER_PLACED}))
  with pytest.raises(OrderNotFound):
    await market(v).cancel_order('5', settings=FAST)
  assert len(v.cancel_actions()) == 1


async def test_disabled_refusal_is_not_retried(venue: Callable[..., Venue]):
  """Without the setting there is no second cancel."""
  v = venue(entry({'error': 'busy'}))
  with pytest.raises(ApiError):
    await market(v).cancel_order('5')
  assert len(v.cancel_actions()) == 1


async def test_cancel_orders_signs_each_fast(venue: Callable[..., Venue]):
  """Bulk cancel by id cancels each order in its own fast action."""
  v = venue(SUCCESS, SUCCESS)
  await market(v).cancel_orders(['5', '6'], settings=FAST)
  actions = v.cancel_actions()
  assert sorted(a['cancels'][0]['o'] for a in actions) == [5, 6]
  assert all(a['f'] is True for a in actions)


@pytest.mark.parametrize('settings,flag', [(FAST, True), ({}, None)])
async def test_cancel_open_orders_follows_the_setting(
  venue: Callable[..., Venue], settings: Settings, flag: bool | None
):
  """The SDK default cancels each open order through `cancel_order`: every one fast with
  the setting, trigger orders included, and none without it."""
  v = venue(SUCCESS, SUCCESS)
  m = market(v, open_orders=[frontend(5, trigger=False), frontend(6, trigger=True)])
  await m.cancel_open_orders(settings=settings)
  sent = {a['cancels'][0]['o']: a.get('f') for a in v.cancel_actions()}
  assert sent == {5: flag, 6: flag}


async def test_replacement_cancel_is_fast(venue: Callable[..., Venue]):
  """A cancel-then-place replacement signs its cancel fast, then places."""
  v = venue(SUCCESS)
  (result,) = await market(v).replace_orders([('5', LIMIT)], settings=FAST)
  assert isinstance(result, OrderResponse) and result.id == '9'
  assert v.cancel_actions() == [
    {'type': 'cancel', 'cancels': [{'a': 3, 'o': 5}], 'f': True}
  ]
  assert [a['type'] for a in v.signed] == ['cancel', 'order']


async def test_replacement_cancel_is_ordinary_when_disabled(
  venue: Callable[..., Venue],
):
  """Without the setting the replacement's cancel carries no flag."""
  v = venue(SUCCESS)
  await market(v).replace_order('5', LIMIT)
  assert v.cancel_actions() == [{'type': 'cancel', 'cancels': [{'a': 3, 'o': 5}]}]
