"""Order placement, modification, cancellation and lookup, shared by perp and spot markets.

The SDK order id is the `client_order_index` assigned at placement: a create-order
transaction only returns its hash (the venue assigns `order_index` on execution), and
the venue accepts the client index wherever it takes an `order_index`.
"""

from decimal import Decimal

from typing_extensions import Any, Sequence
from typed_lighter.core.envelope import INVALID_NONCE, error_code
from typed_lighter.core.exc import BadRequest as ClientBadRequest
from typed_lighter.schemas import SendTxResponse
from typed_lighter.tx.create_order import IocLimitOrder, LimitOrder, MarketOrder
from tribulnation.sdk.core import BadRequest, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings

from ..batching import OrderTx
from ..core import Shared
from .common import parse_order


def refused(exc: BadRequest) -> bool:
  """Whether a submission `BadRequest` is the API layer refusing the transaction.

  `typed_lighter` raises `BadRequest` with Lighter's business code for a refusal the
  sequencer never saw (see `typed_lighter.tx.nonce`). `21104` (invalid nonce), a
  code-less HTTP status and any `5XX` are not certain refusals.
  """
  cause = exc.__cause__
  if not isinstance(cause, ClientBadRequest):
    return False
  code = error_code(cause)
  return code is not None and code != INVALID_NONCE


async def send(shared: Shared, tx: OrderTx) -> SendTxResponse:
  """Send an order transaction through the client's batcher (`batching.TxBatcher`)."""
  return await shared.call(lambda: shared.batcher.submit(tx))


async def submit(shared: Shared, tx: OrderTx) -> SendTxResponse:
  """Send a create-order transaction, raising `OrderRejected` for a certain refusal."""
  try:
    return await send(shared, tx)
  except BadRequest as exc:
    if refused(exc):
      raise OrderRejected(*exc.args) from exc
    raise


async def place_order(
  shared: Shared, market_id: int, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Sign and send a create-order transaction.

  `LIMIT` rests good-till-time (the venue's 28-day default expiry), or is
  immediate-or-cancel (no expiry) with `settings={'lighter': {'time_in_force':
  'immediate-or-cancel'}}`. `POST_ONLY` is rejected rather than taking liquidity, and
  `MARKET` is the venue's market order with `price` as the worst acceptable price.
  Off-grid prices and sizes raise before signing. Acceptance is not execution: a
  sequencer rejection, or an IOC cancelled unfilled, shows as a `canceled-*` status.

  With `settings={'lighter': {'replaces': id}}` it modifies that resting order instead
  (`modify_order`). Order transactions sent while another is in flight go together in
  one `sendTxBatch` (`batching.TxBatcher`).

  Raises:
    ValueError: `time_in_force` is set on a `MARKET` or `POST_ONLY` order.
    OrderRejected: The API refused the transaction with a business code before the
      sequencer saw it (other than `21104` invalid nonce).
    ApiError: The transaction went in a batch that Lighter refused: whether it was
      placed is unknown (`batching.batch_error`).
  """
  lighter = settings.get('lighter', {})
  time_in_force = lighter.get('time_in_force')
  if time_in_force is not None and order['type'] != 'LIMIT':
    raise ValueError(
      f'Lighter time_in_force applies to LIMIT orders only, not {order["type"]}'
    )
  if (replaces := lighter.get('replaces')) is not None:
    if time_in_force is not None or lighter.get('reduce_only'):
      raise ValueError(
        "A Lighter modify keeps the order's time-in-force and reduce-only flag: "
        'drop time_in_force and reduce_only beside replaces'
      )
    return await modify_order(shared, market_id, replaces, order)
  shared.require_api_key()
  scaler = await shared.scaler(market_id)
  qty = Decimal(order['qty'])
  client_index = shared.client_indexes.next()
  base_amount = scaler.size(abs(qty))
  price = scaler.price(Decimal(order['price']))
  reduce_only = lighter.get('reduce_only', False)
  is_ask = qty < 0
  request: LimitOrder | IocLimitOrder | MarketOrder
  if order['type'] == 'MARKET':
    request = {
      'order_type': 'market',
      'market_index': market_id,
      'client_order_index': client_index,
      'base_amount': base_amount,
      'is_ask': is_ask,
      'price': price,
      'reduce_only': reduce_only,
    }
  elif time_in_force == 'immediate-or-cancel':
    request = {
      'order_type': 'limit',
      'market_index': market_id,
      'client_order_index': client_index,
      'base_amount': base_amount,
      'is_ask': is_ask,
      'price': price,
      'time_in_force': 'immediate-or-cancel',
      'reduce_only': reduce_only,
    }
  else:
    request = {
      'order_type': 'limit',
      'market_index': market_id,
      'client_order_index': client_index,
      'base_amount': base_amount,
      'is_ask': is_ask,
      'price': price,
      'time_in_force': 'post-only'
      if order['type'] == 'POST_ONLY'
      else 'good-till-time',
      'reduce_only': reduce_only,
    }
  response = await submit(
    shared,
    OrderTx(
      send=lambda: shared.client.tx.create_order(request),
      sign=lambda key, nonce: shared.client.signer.create_order(
        request, api_key_index=key, nonce=nonce
      ),
    ),
  )
  return OrderResponse(id=str(client_index), details=response)


async def modify_order(
  shared: Shared, market_id: int, id: str, order: Order
) -> OrderResponse:
  """Move a resting order to `order`'s price and size with one `L2ModifyOrder`.

  One transaction, where cancelling and placing again takes two. The order keeps its id
  (the response's), side, time-in-force and reduce-only flag: a post-only order stays
  post-only, and neither `order`'s type (other than `MARKET`) nor the sign of its `qty`
  is checked against it. Acceptance is not execution: if the order is gone by then, the
  sequencer drops the modify, and the response says nothing of it.

  Args:
    shared: The owner of the client.
    market_id: The venue's market id.
    id: The resting order's SDK id (its client order index).
    order: The order's new price and size.

  Raises:
    ValueError: `order` is a `MARKET` order, or `id` is not a client order index.
    BadRequest: The API refused the transaction; the order rests unchanged.
    ApiError: The modify went in a batch that Lighter refused.
  """
  if order['type'] == 'MARKET':
    raise ValueError('Lighter can only modify a resting LIMIT or POST_ONLY order')
  shared.require_api_key()
  index = client_index(id)
  scaler = await shared.scaler(market_id)
  base_amount = scaler.size(abs(Decimal(order['qty'])))
  price = scaler.price(Decimal(order['price']))
  response = await send(
    shared,
    OrderTx(
      send=lambda: shared.client.tx.modify_order(
        market_index=market_id, order_index=index, base_amount=base_amount, price=price
      ),
      sign=lambda key, nonce: shared.client.signer.modify_order(
        market_index=market_id,
        order_index=index,
        base_amount=base_amount,
        price=price,
        api_key_index=key,
        nonce=nonce,
      ),
    ),
  )
  return OrderResponse(id=id, details=response)


def client_index(id: str) -> int:
  """An SDK order id as the venue's client order index."""
  try:
    return int(id)
  except ValueError:
    raise ValueError(f'Lighter order ids are client order indexes: {id!r}') from None


async def cancel_order(shared: Shared, market_id: int, id: str) -> SendTxResponse:
  """Cancel by client order index, alone or batched with other order transactions."""
  shared.require_api_key()
  index = client_index(id)
  return await send(
    shared,
    OrderTx(
      send=lambda: shared.client.tx.cancel_order(
        market_index=market_id, order_index=index
      ),
      sign=lambda key, nonce: shared.client.signer.cancel_order(
        market_index=market_id, order_index=index, api_key_index=key, nonce=nonce
      ),
    ),
  )


async def query_order(shared: Shared, market_id: int, id: str) -> OrderState | None:
  """Look an order up by client index: active orders, and inactive ones of the last 24h.

  A cancelled order leaves the active set seconds before it is indexed as inactive; in
  that window, and after 24h, it is not found.
  """
  index, account = client_index(id), shared.private_index
  orders = await shared.call(
    lambda: shared.client.api.account.orders.by_client_index(
      [index], account_index=account
    )
  )
  for o in orders['orders']:
    if o['market_index'] == market_id:
      return parse_order(o)


async def open_orders(shared: Shared, market_id: int) -> Sequence[OrderState]:
  """The market's active orders."""
  account = shared.private_index
  orders = await shared.call(
    lambda: shared.client.api.account.orders.active(
      account_index=account, market_id=market_id
    )
  )
  return [parse_order(o) for o in orders['orders']]
