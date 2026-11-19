"""Order placement, cancellation and lookup.

The SDK order id is the venue's order id, `DDDDD:<26 hex>`, which the placing client
chooses: `place_order` sends the order's `client_order_id` as that id, or a fresh one.
Placement is asynchronous on the venue: the reply's `NEW` means the order was accepted,
not that it executed.
"""

from decimal import Decimal

from typing_extensions import Any, Sequence
from typed_evedex.exchange.market.instruments import InstrumentInfo
from typed_evedex.schemas import NewOrder
from tribulnation.sdk.core import BadRequest, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, OrderState
from tribulnation.sdk.util import to_decimal

from ..core import ORDER_ID, Shared, venue_label
from .common import parse_order

POST_ONLY_REFUSED = (
  'EVEDEX refuses post-only orders (`post_only_not_allowed_error` on mainnet and demo, '
  '2026-11-19)'
)
NOT_FOUND = 'order_not_found_error'
"""The label of a cancel or lookup of an order id the venue does not know."""


def on_grid(*, value: Decimal, step: Decimal, what: str, name: str):
  """Check `value` is a whole number of `step`s.

  Raises:
    ValueError: `value` is not a multiple of `step`.
  """
  if (value / step) != (value / step).to_integral_value():
    raise ValueError(f'EVEDEX {name}: {what} {value} is not a multiple of {step}')


def checked(instrument: InstrumentInfo, order: Order) -> tuple[Decimal, Decimal]:
  """The order's signed quantity and price, checked before signing.

  The client would round both half-up to 8 decimals and sign the result, so an
  off-grid value is refused here instead of being moved.

  Raises:
    ValueError: Zero size, a non-positive price, an off-grid price or size, or a
      client order id that is not a venue order id (`DDDDD:<26 hex>`).
  """
  name = instrument['name']
  qty, price = to_decimal(order['qty']), to_decimal(order['price'])
  if qty == 0:
    raise ValueError(f'EVEDEX {name}: an order needs a non-zero qty')
  if price <= 0:
    raise ValueError(f'EVEDEX {name}: an order needs a positive price, not {price}')
  on_grid(value=abs(qty), step=instrument['quantityIncrement'], what='qty', name=name)
  on_grid(value=price, step=instrument['priceIncrement'], what='price', name=name)
  client_id = order.get('client_order_id')
  if client_id is not None and not ORDER_ID.match(client_id):
    raise ValueError(
      f'EVEDEX client order ids are venue order ids (`DDDDD:<26 hex>`), not {client_id!r}'
    )
  return qty, price


async def place_order(
  shared: Shared, instrument: InstrumentInfo, order: Order, *, leverage: int
) -> OrderResponse:
  """Sign and send one limit order at the account's leverage on the instrument.

  `LIMIT` is good-till-cancelled and `MARKET` an immediate-or-cancel limit at `price`
  (the venue's own market order is sized in USD and bounded only by the instrument's
  slippage limit); a non-crossing IOC limit ends `CANCELLED`, nothing resting (mainnet,
  2026-11-19). The venue reports no execution at placement, so `filled_qty` is `None`.

  Raises:
    NotImplementedError: A `POST_ONLY` order: EVEDEX refuses `postOnly` with
      `post_only_not_allowed_error` (mainnet and demo, 2026-11-19).
    AuthError: The client has no wallet key.
    ValueError: See `checked`.
    OrderRejected: The venue refused the order: nothing rests.
  """
  kind = order['type']
  if kind == 'POST_ONLY':
    raise NotImplementedError(POST_ONLY_REFUSED)
  qty, price = checked(instrument, order)
  shared.require_wallet()
  client_id = order.get('client_order_id')

  async def send() -> NewOrder:
    """Place the order."""
    return await shared.client.exchange.orders.place_limit(
      instrument=instrument['name'],
      side='BUY' if qty > 0 else 'SELL',
      leverage=leverage,
      quantity=abs(qty),
      limit_price=price,
      time_in_force='IOC' if kind == 'MARKET' else None,
      id=client_id,
    )

  try:
    placed = await shared.call(send)
  except BadRequest as exc:
    raise OrderRejected(*exc.args) from exc
  if placed['status'] in ('REJECTED', 'ERROR'):
    raise OrderRejected(placed['status'], placed.get('rejectedReason'), placed)
  return OrderResponse(id=placed['id'], details=placed)


async def cancel_order(shared: Shared, id: str) -> Any:
  """Cancel one order; an order filled before the cancel is processed stays filled.

  Raises:
    AuthError: The client is public.
    OrderNotFound: The venue does not know the id.
  """
  shared.require_account()
  try:
    return await shared.call(lambda: shared.client.exchange.orders.cancel(id))
  except BadRequest as exc:
    if venue_label(exc) == NOT_FOUND:
      raise OrderNotFound(*exc.args) from exc
    raise


async def cancel_open_orders(shared: Shared, instrument: str) -> Any:
  """Cancel every open order of the account on the instrument, in one request.

  Raises:
    AuthError: The client is public.
  """
  shared.require_account()
  return await shared.call(
    lambda: shared.client.exchange.orders.cancel_by_instrument(instrument)
  )


async def query_order(shared: Shared, instrument: str, id: str) -> OrderState | None:
  """Look an order up by id, open or closed; `None` when the venue does not know it or
  it belongs to another instrument."""
  shared.require_account()
  try:
    found = await shared.call(lambda: shared.client.exchange.orders.get(id))
  except BadRequest as exc:
    if venue_label(exc) != NOT_FOUND:
      raise
  else:
    if found['instrument'] == instrument:
      return parse_order(found)


async def open_orders(shared: Shared, instrument: str) -> Sequence[OrderState]:
  """The account's open orders on the instrument (`orders.opened`, every instrument in
  one reply)."""
  shared.require_account()
  rows = await shared.call(shared.client.exchange.orders.opened)
  return [parse_order(o) for o in rows if o['instrument'] == instrument]
