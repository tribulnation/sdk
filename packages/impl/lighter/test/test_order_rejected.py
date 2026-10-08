"""`place_order` raises `OrderRejected` only for Lighter's definitive refusals."""

from dataclasses import dataclass, field
from typing_extensions import Any, cast

import pytest
from typed_lighter import Lighter
from typed_lighter.core.envelope import raise_code
from typed_lighter.core.exc import (
  ApiError as ClientApiError,
  BadRequest as ClientBadRequest,
)
from typed_lighter.scaling import Scaler

from tribulnation.lighter.core import Shared
from tribulnation.lighter.market import orders
from tribulnation.sdk.core import ApiError, BadRequest, OrderRejected, RateLimited
from tribulnation.sdk.market import Order

MARKET = 4095
ORDER: Order = {'qty': '-0.01', 'price': '2500.5', 'type': 'POST_ONLY'}


def coded(code: int, *, server_error: bool = False) -> ClientApiError:
  """The exception `typed_lighter` raises for a business code."""
  try:
    raise_code(code, 'refused', {'code': code}, server_error=server_error)
  except ClientApiError as e:
    return e


@dataclass
class Tx:
  """Fail every create-order transaction with `error`."""

  error: Exception

  async def create_order(self, request: dict[str, Any]) -> dict[str, Any]:
    """Raise the configured error."""
    raise self.error


@dataclass
class Client:
  """The client attributes `place_order` reaches."""

  tx: Tx
  account_signer: object = field(default_factory=object)


def shared(error: Exception) -> Shared:
  """A market's shared state whose submissions fail with `error`."""
  out = Shared(client=cast(Lighter, Client(tx=Tx(error))))
  out.scalers[MARKET] = Scaler(
    market_id=MARKET, symbol='ETH', price_decimals=2, size_decimals=4
  )
  return out


@pytest.mark.parametrize('code', [21701, 21739, 20001])
async def test_business_code_refusal_is_rejected(code: int):
  """A coded `BadRequest` was refused before the sequencer saw it."""
  with pytest.raises(OrderRejected) as raised:
    await orders.place_order(shared(coded(code)), MARKET, ORDER)

  assert raised.value.args[0] == code


@pytest.mark.parametrize(
  'error',
  [
    coded(21104),
    ClientBadRequest(400, 'Bad Request', None),
  ],
  ids=['invalid-nonce', 'code-less-status'],
)
async def test_uncertain_bad_request_is_not_rejected(error: Exception):
  """An invalid nonce or a code-less HTTP status leaves the outcome unknown."""
  with pytest.raises(BadRequest) as raised:
    await orders.place_order(shared(error), MARKET, ORDER)

  assert not isinstance(raised.value, OrderRejected)


@pytest.mark.parametrize(
  'error',
  [coded(21701, server_error=True), ClientApiError(502, 'Bad Gateway', None)],
  ids=['coded-5xx', 'plain-5xx'],
)
async def test_server_error_is_not_rejected(error: Exception):
  """A `5XX` may hide an accepted transaction, whatever its body says."""
  with pytest.raises(ApiError) as raised:
    await orders.place_order(shared(error), MARKET, ORDER)

  assert not isinstance(raised.value, OrderRejected)


async def test_rate_limit_keeps_its_class():
  """Throttling stays `RateLimited`, the class callers retry on."""
  with pytest.raises(RateLimited):
    await orders.place_order(shared(coded(21506)), MARKET, ORDER)
