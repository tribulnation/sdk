"""Create-order requests built from SDK orders."""

from dataclasses import dataclass, field
from typing_extensions import Any, cast

import pytest
from typed_lighter import Lighter
from typed_lighter.scaling import Scaler

from tribulnation.lighter.core import ClientIndexes, Shared
from tribulnation.lighter.market import orders
from tribulnation.sdk.market import Order

MARKET = 4095


class FixedIndexes(ClientIndexes):
  """Always the same client order index, so requests compare equal."""

  def next(self) -> int:
    """The fixture index."""
    return 7


@dataclass
class Tx:
  """Record create-order requests instead of signing them."""

  requests: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

  async def create_order(self, request: dict[str, Any]) -> dict[str, Any]:
    """Record the request."""
    self.requests.append(request)
    return {'code': 200, 'tx_hash': 'ab'}


@dataclass
class Client:
  """The client attributes `place_order` reaches."""

  tx: Tx = field(default_factory=Tx)
  account_signer: object = field(default_factory=object)
  """Any signer: trading checks one is configured."""


@pytest.mark.parametrize('type', ['LIMIT', 'POST_ONLY', 'MARKET'])
async def test_client_order_id_leaves_the_request_unchanged(type: Any):
  """The SDK id is the client order index, so a caller's id is ignored."""
  client = Client()
  shared = Shared(client=cast(Lighter, client), client_indexes=FixedIndexes())
  shared.scalers[MARKET] = Scaler(
    market_id=MARKET, symbol='ETH', price_decimals=2, size_decimals=4
  )
  order: Order = {'qty': '-0.01', 'price': '2500.5', 'type': type}
  plain = await orders.place_order(shared, MARKET, order)
  tagged = await orders.place_order(
    shared, MARKET, {**order, 'client_order_id': 'my-order'}
  )
  first, second = client.tx.requests
  assert first == second and first['client_order_index'] == 7
  assert plain.id == tagged.id == '7'


def ioc_shared(client: Client) -> Shared:
  """Shared state over `client` with the fixture market's scaler."""
  shared = Shared(client=cast(Lighter, client), client_indexes=FixedIndexes())
  shared.scalers[MARKET] = Scaler(
    market_id=MARKET, symbol='ETH', price_decimals=2, size_decimals=4
  )
  return shared


async def test_ioc_setting_makes_limit_immediate_or_cancel():
  """`time_in_force` sends an IOC limit with no expiry; without it LIMIT stays GTT."""
  client = Client()
  shared = ioc_shared(client)
  order: Order = {'qty': '0.01', 'price': '2500.5', 'type': 'LIMIT'}
  response = await orders.place_order(
    shared,
    MARKET,
    order,
    settings={'lighter': {'time_in_force': 'immediate-or-cancel'}},
  )
  await orders.place_order(shared, MARKET, order)
  ioc, gtt = client.tx.requests
  assert response.id == '7'
  assert ioc == {
    'order_type': 'limit',
    'market_index': MARKET,
    'client_order_index': 7,
    'base_amount': 100,
    'is_ask': False,
    'price': 250050,
    'time_in_force': 'immediate-or-cancel',
    'reduce_only': False,
  }
  assert gtt == {**ioc, 'time_in_force': 'good-till-time'}


async def test_ioc_setting_keeps_reduce_only():
  """Both Lighter settings combine."""
  client = Client()
  order: Order = {'qty': '-0.01', 'price': '2500.5', 'type': 'LIMIT'}
  await orders.place_order(
    ioc_shared(client),
    MARKET,
    order,
    settings={'lighter': {'time_in_force': 'immediate-or-cancel', 'reduce_only': True}},
  )
  (request,) = client.tx.requests
  assert request['time_in_force'] == 'immediate-or-cancel'
  assert request['reduce_only'] is True and request['is_ask'] is True


@pytest.mark.parametrize('type', ['POST_ONLY', 'MARKET'])
async def test_ioc_setting_rejects_other_order_types(type: Any):
  """The setting applies to LIMIT only; elsewhere it raises before anything is sent."""
  client = Client()
  order: Order = {'qty': '0.01', 'price': '2500.5', 'type': type}
  with pytest.raises(ValueError, match='LIMIT orders only'):
    await orders.place_order(
      ioc_shared(client),
      MARKET,
      order,
      settings={'lighter': {'time_in_force': 'immediate-or-cancel'}},
    )
  assert client.tx.requests == []
