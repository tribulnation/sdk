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
