"""Order placement, cancellation, replacement and lookup.

The SDK order id is the order's digest, the id Nado queries and cancels by. A
`client_order_id` is sent as the order's `id`, an integer the venue echoes on order
queries and fill events but does not keep unique.
"""

from decimal import Decimal

from typing_extensions import Any, Mapping, Sequence
from typed_nado import order_appendix
from typed_nado.core.appendix import OrderType
from typed_nado.schemas import Order as NadoOrder, PlaceOrderRequest, Symbol
from tribulnation.sdk.core import BadRequest, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings

from ..core import GTC_EXPIRATION, Shared, to_x18
from .common import parse_archived_order, parse_open_order

NOT_FOUND = 2020
"""`gateway.order` for a digest no longer on the book (filled, cancelled or unknown)."""
ORDER_TYPES: Mapping[str, OrderType] = {
  'LIMIT': 'default',
  'POST_ONLY': 'post_only',
  'MARKET': 'ioc',
}
"""The appendix order type of each SDK order type: Nado has no market order, so
`MARKET` is an immediate-or-cancel limit at the SDK `price`, the worst acceptable."""
CLIENT_ID_LIMIT = 2**64
"""Client ids must fit an unsigned 64-bit integer."""


def spot_leverage(symbol: Symbol, settings: Settings) -> bool | None:
  """Whether the order may borrow: never on spot, unless `{'nado': {'spot_leverage':
  True}}` says so; perpetual orders send nothing (the venue's default)."""
  if symbol['type'] != 'spot':
    return None
  return settings.get('nado', {}).get('spot_leverage', False)


def client_id(order: Order) -> int | None:
  """The order's `client_order_id` as the venue's integer `id`.

  Raises:
    ValueError: It is not a decimal integer in `[0, 2^64)`.
  """
  raw = order.get('client_order_id')
  if raw is None:
    return None
  try:
    value = int(raw)
  except ValueError:
    raise ValueError(f'Nado client order ids are integers, got {raw!r}') from None
  if not 0 <= value < CLIENT_ID_LIMIT:
    raise ValueError(f'Nado client order ids fit 64 unsigned bits, got {raw!r}')
  return value


def nado_order(order: Order) -> NadoOrder:
  """The signed order struct for an SDK order: a limit at `price`, expiring with
  `GTC_EXPIRATION`, with the appendix of its type.

  Raises:
    ValueError: The quantity is zero or not finite, or the price is not positive.
  """
  qty = Decimal(str(order['qty']))
  price = Decimal(str(order['price']))
  if not qty.is_finite() or not qty:
    raise ValueError('Order quantity must be finite and nonzero')
  if not price.is_finite() or price <= 0:
    raise ValueError('Order price must be finite and positive')
  return {
    'priceX18': to_x18(price),
    'amount': to_x18(qty),
    'expiration': GTC_EXPIRATION,
    'appendix': order_appendix(ORDER_TYPES[order['type']]),
  }


def place_request(
  symbol: Symbol, order: Order, settings: Settings
) -> PlaceOrderRequest:
  """One `place_orders`/`cancel_and_place` entry for an SDK order."""
  request: PlaceOrderRequest = {
    'product_id': symbol['product_id'],
    'order': nado_order(order),
  }
  if (borrow := spot_leverage(symbol, settings)) is not None:
    request['spot_leverage'] = borrow
  if (id := client_id(order)) is not None:
    request['id'] = id
  return request


def rejected(exc: BadRequest) -> OrderRejected:
  """The `OrderRejected` for a coded refusal.

  The sequencer validates an order synchronously and answers with an error code
  before the order exists (`2000` off-tick price, `2094` below the minimum notional,
  `2056` an IOC that does not cross, health and post-only checks, ...): a coded
  `BadRequest` from a placement is always a refusal.
  """
  return OrderRejected(*exc.args)


def coded(exc: BadRequest) -> bool:
  """Whether a `BadRequest` carries the venue's error code (`(code, message, body)`)."""
  return len(exc.args) == 3 and isinstance(exc.args[0], int)


async def place_order(
  shared: Shared, symbol: Symbol, order: Order, settings: Settings
) -> OrderResponse:
  """Sign and send one order; its digest is the SDK id.

  Raises:
    AuthError: The client has no key to sign with.
    OrderRejected: The venue refused the order.
  """
  shared.require_signer()
  request = place_request(symbol, order, settings)
  try:
    reply = await shared.call(lambda: shared.client.gateway.place_order(**request))
  except BadRequest as exc:
    if coded(exc):
      raise rejected(exc) from exc
    raise
  return OrderResponse(id=reply['digest'], details=reply)


async def place_orders(
  shared: Shared, symbol: Symbol, orders: Sequence[Order], settings: Settings
) -> list[OrderResponse | Exception]:
  """Sign every order and send them in one `place_orders`, processed independently.

  An order the venue refused comes back as `OrderRejected` with the venue's message;
  an order that could not be built (a bad quantity, price or client id) as its
  `ValueError`, and is not sent. The venue validates the whole batch first, so one
  invalid order refuses every order sent with it: each comes back as that
  `OrderRejected`.

  Raises:
    AuthError: The client has no key to sign with.
  """
  shared.require_signer()
  results: list[OrderResponse | Exception | None] = []
  requests: list[PlaceOrderRequest] = []
  for order in orders:
    try:
      requests.append(place_request(symbol, order, settings))
      results.append(None)
    except ValueError as exc:
      results.append(exc)
  if not requests:
    return [r for r in results if r is not None]
  try:
    replies = await shared.call(lambda: shared.client.gateway.place_orders(requests))
  except BadRequest as exc:
    if not coded(exc):
      raise
    # The sequencer validates the whole batch before placing any of it: one off-tick
    # order refused all three of a batch, and none rested (mainnet, 2026-11-17).
    refusal = rejected(exc)
    return [refusal if r is None else r for r in results]
  sent = iter(replies)
  out: list[OrderResponse | Exception] = []
  for result in results:
    if result is not None:
      out.append(result)
      continue
    reply = next(sent)
    if reply['digest'] is not None:
      out.append(OrderResponse(id=reply['digest'], details=reply))
    else:
      out.append(OrderRejected(None, reply['error'] or 'refused', reply))
  return out


async def cancel_orders(shared: Shared, product_id: int, ids: Sequence[str]) -> Any:
  """Cancel by digest, in one signed `Cancellation`; the reply lists what was removed."""
  shared.require_signer()
  return await shared.call(
    lambda: shared.client.gateway.cancel_orders(
      {'productIds': [product_id] * len(ids), 'digests': list(ids)}
    )
  )


async def cancel_order(shared: Shared, product_id: int, id: str) -> Any:
  """Cancel one order by digest.

  Raises:
    OrderNotFound: The venue removed nothing: the digest is no longer on the book
      (filled, cancelled or unknown). Nado answers such a cancel with an empty
      `cancelled_orders` rather than an error (mainnet, 2026-11-17).
  """
  reply = await cancel_orders(shared, product_id, [id])
  if not any(o['digest'] == id for o in reply['cancelled_orders']):
    raise OrderNotFound(None, f'Nado order {id} is not on the book', reply)
  return reply


async def cancel_open_orders(shared: Shared, product_id: int) -> Any:
  """The venue's cancel-all (`CancellationProducts`), scoped to the product."""
  shared.require_signer()
  return await shared.call(
    lambda: shared.client.gateway.cancel_product_orders({'productIds': [product_id]})
  )


async def replace_order(
  shared: Shared, symbol: Symbol, id: str, order: Order, settings: Settings
) -> OrderResponse:
  """Cancel `id` and place `order` atomically (`cancel_and_place`): the new order loses
  `id`'s queue priority.

  The two legs succeed or fail together: when the venue refuses `order`, `id` keeps
  resting (an off-tick replacement left the original on the book, mainnet,
  2026-11-17), so the refusal is the venue's `BadRequest`, never `OrderRejected`
  (which would mean `id` is gone).

  Raises:
    AuthError: The client has no key to sign with.
    BadRequest: The venue refused the replacement; `id` still rests.
  """
  shared.require_signer()
  request = place_request(symbol, order, settings)
  reply = await shared.call(
    lambda: shared.client.gateway.cancel_and_place(
      {'productIds': [symbol['product_id']], 'digests': [id]}, place_order=request
    )
  )
  return OrderResponse(id=reply['digest'], details=reply)


async def open_orders(shared: Shared, product_id: int) -> Sequence[OrderState]:
  """The subaccount's resting orders on the product."""
  sender = shared.require_sender()
  reply = await shared.call(
    lambda: shared.client.gateway.subaccount_orders(sender, product_id=product_id)
  )
  return [parse_open_order(o) for o in reply['orders']]


async def query_order(shared: Shared, product_id: int, id: str) -> OrderState | None:
  """An order by digest: from the book while it rests, else from the archive, which
  indexes only orders that filled at least once.

  An order cancelled without any fill, an unknown digest, or one on another product or
  subaccount is `None`.
  """
  sender = shared.require_sender()
  try:
    o = await shared.call(lambda: shared.client.gateway.order(product_id, digest=id))
  except BadRequest as exc:
    if not exc.args or exc.args[0] != NOT_FOUND:
      raise
  else:
    return parse_open_order(o) if o['sender'].lower() == sender.lower() else None
  archived = await shared.call(lambda: shared.client.archive.orders(digests=[id]))
  for row in archived['orders']:
    if row['product_id'] == product_id and row['subaccount'].lower() == sender.lower():
      return parse_archived_order(row)
  return None
