"""Order transactions sent while another is in flight leave together in one `sendTxBatch`."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing_extensions import Any, AsyncIterator, cast
import asyncio

import pytest
from typed_lighter import Lighter
from typed_lighter.core.envelope import raise_code
from typed_lighter.core.exc import ApiError as ClientApiError
from typed_lighter.core.exc import RateLimited as ClientRateLimited
from typed_lighter.scaling import Scaler

from tribulnation.lighter.batching import BATCH_LIMIT
from tribulnation.lighter.core import ClientIndexes, Shared
from tribulnation.lighter.market import orders
from tribulnation.sdk.core import (
  ApiError,
  BadRequest,
  NetworkError,
  OrderRejected,
  RateLimited,
)
from tribulnation.sdk.market import Order

MARKET = 4095
KEY = 4
ORDER: Order = {'qty': '0.01', 'price': '2500.5', 'type': 'POST_ONLY'}


class FixedIndexes(ClientIndexes):
  """Always the same client order index."""

  def next(self) -> int:
    """The fixture index."""
    return 7


@dataclass
class Tx:
  """Record transactions sent alone and in batches; `hold` keeps a send in flight."""

  singles: list[tuple[str, dict[str, Any]]] = field(
    default_factory=list[tuple[str, dict[str, Any]]]
  )
  batches: list[list[Any]] = field(default_factory=list[list[Any]])
  hold: asyncio.Event | None = None
  """While set to an unset event, every send waits for it."""
  error: Exception | None = None
  """Raised by every batch."""
  next_nonce: int = 10

  async def single(self, kind: str, request: dict[str, Any]) -> dict[str, Any]:
    """Record one transaction sent alone."""
    self.singles.append((kind, request))
    if self.hold is not None:
      await self.hold.wait()
    return {'code': 200, 'tx_hash': f'single-{len(self.singles)}'}

  async def create_order(self, request: dict[str, Any]) -> dict[str, Any]:
    """`client.tx.create_order`."""
    return await self.single('create', request)

  async def modify_order(self, **request: Any) -> dict[str, Any]:
    """`client.tx.modify_order`."""
    return await self.single('modify', request)

  async def cancel_order(self, **request: Any) -> dict[str, Any]:
    """`client.tx.cancel_order`."""
    return await self.single('cancel', request)

  @asynccontextmanager
  async def reserve_nonces(self, count: int) -> AsyncIterator[SimpleNamespace]:
    """Hold the next `count` nonces of the fixture key."""
    first = self.next_nonce
    self.next_nonce += count
    yield SimpleNamespace(api_key_index=KEY, nonces=range(first, first + count))

  async def batch(self, signed: list[Any]) -> dict[str, Any]:
    """Record a batch and accept it, or raise `error`."""
    self.batches.append(signed)
    if self.hold is not None:
      await self.hold.wait()
    if self.error is not None:
      raise self.error
    return {
      'code': 200,
      'tx_hash': [f'hash-{nonce}' for *_, nonce in signed],
      'predicted_execution_time_ms': 1,
    }


class Signer:
  """Sign transactions as (kind, request, key, nonce) tuples."""

  def create_order(self, order: dict[str, Any], *, api_key_index: int, nonce: int):
    """Sign a create."""
    return ('create', order, api_key_index, nonce)

  def modify_order(self, *, api_key_index: int, nonce: int, **request: Any):
    """Sign a modify."""
    return ('modify', request, api_key_index, nonce)

  def cancel_order(self, *, api_key_index: int, nonce: int, **request: Any):
    """Sign a cancel."""
    return ('cancel', request, api_key_index, nonce)


@dataclass
class Client:
  """The client attributes order transactions reach."""

  tx: Tx = field(default_factory=Tx)
  signer: Signer = field(default_factory=Signer)
  account_signer: object = field(default_factory=object)


def shared(client: Client) -> Shared:
  """Shared state over `client` with the fixture market's scaler."""
  out = Shared(client=cast(Lighter, client), client_indexes=FixedIndexes())
  out.scalers[MARKET] = Scaler(
    market_id=MARKET, symbol='ETH', price_decimals=2, size_decimals=4
  )
  return out


def coded(code: int) -> ClientApiError:
  """The exception `typed_lighter` raises for a business code."""
  try:
    raise_code(code, 'refused', {'code': code})
  except ClientApiError as e:
    return e


async def test_a_lone_transaction_goes_alone():
  """With nothing else waiting, an order is one plain `sendTx`, as without batching."""
  client = Client()
  response = await orders.place_order(shared(client), MARKET, ORDER)
  assert response.id == '7' and response.details['tx_hash'] == 'single-1'
  assert [kind for kind, _ in client.tx.singles] == ['create']
  assert client.tx.batches == []


async def test_transactions_of_one_turn_leave_in_one_batch():
  """A create, a modify and a cancel sent together: one batch, consecutive nonces."""
  client = Client()
  s = shared(client)
  created, modified, cancelled = await asyncio.gather(
    orders.place_order(s, MARKET, ORDER),
    orders.place_order(s, MARKET, ORDER, settings={'lighter': {'replaces': '42'}}),
    orders.cancel_order(s, MARKET, '43'),
  )
  assert client.tx.singles == []
  ((create, modify, cancel),) = client.tx.batches
  assert [(kind, key, nonce) for kind, _, key, nonce in (create, modify, cancel)] == [
    ('create', KEY, 10),
    ('modify', KEY, 11),
    ('cancel', KEY, 12),
  ]
  assert create[1]['time_in_force'] == 'post-only'
  assert modify[1] == {
    'market_index': MARKET,
    'order_index': 42,
    'base_amount': 100,
    'price': 250050,
  }
  assert cancel[1] == {'market_index': MARKET, 'order_index': 43}
  assert created.id == '7' and created.details['tx_hash'] == 'hash-10'
  assert modified.id == '42' and modified.details['tx_hash'] == 'hash-11'
  assert cancelled['tx_hash'] == 'hash-12' and cancelled['code'] == 200


async def test_transactions_waiting_behind_one_in_flight_leave_together():
  """The first goes alone; the two sent while it is in flight follow in one batch."""
  client = Client()
  client.tx.hold = asyncio.Event()
  s = shared(client)
  first = asyncio.create_task(orders.cancel_order(s, MARKET, '1'))
  while not client.tx.singles:
    await asyncio.sleep(0)
  rest = asyncio.gather(
    orders.cancel_order(s, MARKET, '2'), orders.cancel_order(s, MARKET, '3')
  )
  await asyncio.sleep(0.01)
  client.tx.hold.set()
  await first
  await rest
  assert [r['order_index'] for _, r in client.tx.singles] == [1]
  ((two, three),) = client.tx.batches
  assert (two[1]['order_index'], three[1]['order_index']) == (2, 3)


async def test_a_batch_holds_at_most_the_limit():
  """More transactions than one batch takes leave in several, in order."""
  client = Client()
  s = shared(client)
  count = BATCH_LIMIT + 5
  await asyncio.gather(*[orders.cancel_order(s, MARKET, str(i)) for i in range(count)])
  assert [len(b) for b in client.tx.batches] == [BATCH_LIMIT, 5]
  sent = [tx[1]['order_index'] for b in client.tx.batches for tx in b]
  assert sent == list(range(count))


async def test_a_refused_batch_leaves_each_order_unknown():
  """A refusal names no transaction: each create gets `ApiError`, not `OrderRejected`."""
  client = Client()
  client.tx.error = coded(21701)
  s = shared(client)
  results = await asyncio.gather(
    orders.place_order(s, MARKET, ORDER),
    orders.place_order(s, MARKET, ORDER),
    return_exceptions=True,
  )
  for result in results:
    assert isinstance(result, ApiError)
    assert not isinstance(result, (BadRequest, OrderRejected))


async def test_a_lone_refusal_stays_a_rejection():
  """Sent alone, a coded refusal of a create is still `OrderRejected`."""

  class Refusing(Tx):
    async def create_order(self, request: dict[str, Any]) -> dict[str, Any]:
      raise coded(21701)

  with pytest.raises(OrderRejected):
    await orders.place_order(shared(Client(tx=Refusing())), MARKET, ORDER)


async def test_a_rate_limited_batch_is_rate_limited_for_each():
  """Failures other than a refusal reach every transaction unchanged."""
  client = Client()
  client.tx.error = ClientRateLimited('slow down')
  s = shared(client)
  results = await asyncio.gather(
    orders.cancel_order(s, MARKET, '1'),
    orders.cancel_order(s, MARKET, '2'),
    return_exceptions=True,
  )
  assert all(isinstance(r, RateLimited) for r in results)


async def test_cancelling_a_waiting_call_drops_its_transaction():
  """A call cancelled before its transaction leaves sends nothing for it."""
  client = Client()
  client.tx.hold = asyncio.Event()
  s = shared(client)
  first = asyncio.create_task(orders.cancel_order(s, MARKET, '1'))
  while not client.tx.singles:
    await asyncio.sleep(0)
  dropped = asyncio.create_task(orders.cancel_order(s, MARKET, '2'))
  kept = asyncio.create_task(orders.cancel_order(s, MARKET, '3'))
  await asyncio.sleep(0.01)
  dropped.cancel()
  client.tx.hold.set()
  await asyncio.gather(first, kept)
  sent = [r['order_index'] for _, r in client.tx.singles]
  assert sent == [1, 3] and client.tx.batches == []


async def test_closing_fails_what_is_in_flight_or_waiting():
  """Closing the client stops the batcher: its transactions fail with `NetworkError`."""
  client = Client()
  client.tx.hold = asyncio.Event()
  s = shared(client)
  async with s.batcher.closing():
    first = asyncio.create_task(orders.cancel_order(s, MARKET, '1'))
    while not client.tx.singles:
      await asyncio.sleep(0)
    waiting = asyncio.create_task(orders.cancel_order(s, MARKET, '2'))
    await asyncio.sleep(0.01)
  results = await asyncio.gather(first, waiting, return_exceptions=True)
  assert all(isinstance(r, NetworkError) for r in results)
