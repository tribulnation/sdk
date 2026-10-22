"""Order placement, cancellation and lookup.

The SDK order id is the order's client order id: `create_order` answers `PENDING` with
the placeholder `order_id` `0x00` (the venue assigns the real one when it processes the
order), while order lookups, cancellations and fills all carry the client order id.
"""

from decimal import Decimal

from typing_extensions import Any, Sequence, cast
from typed_grvt.schemas import LimitOrder, MarketOrder, NewOrder, Order as GrvtOrder
from tribulnation.sdk.core import BadRequest, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, OrderState

from ..core import Shared, random_client_order_id
from .common import parse_order, scope

NOT_FOUND = 1004
"""`Data Not Found`: an order lookup by an unknown client order id."""
OVERLAPPING_CLIENT_ORDER_ID = 2012
"""`Client Order ID overlaps with existing active order`: the id may be the caller's own
earlier attempt, accepted, so the refusal says nothing about whether that order lives."""
CANCEL_BATCH = 100
"""Most client order ids one `bulk_orders` cancel takes."""


def refused(exc: BadRequest) -> bool:
  """Whether a `create_order` failure is the venue refusing the order outright.

  The gateway answers order validation synchronously (`2064` off-tick price, `2065`
  size off the step, `2066` below the minimum notional, margin and reduce-only checks,
  ...) with a `4XX` carrying its code, before the order exists. Such a `BadRequest`
  carries `(code, message, body)`; client-side checks and non-JSON errors do not.
  `2012` is excluded: the order holding that client order id may be the caller's own.
  """
  if len(exc.args) != 3:
    return False
  code, _, body = exc.args
  if not isinstance(code, int) or not isinstance(body, dict):
    return False
  return (
    cast(dict[str, Any], body).get('code') == code
    and code != OVERLAPPING_CLIENT_ORDER_ID
  )


def new_order(instrument: str, order: Order, client_order_id: str) -> NewOrder:
  """The venue order for an SDK order.

  `MARKET` is the venue's market order, immediate-or-cancel: the venue refuses a market
  order with a limit price (`2020`), so the SDK `price` is not sent. `LIMIT` and
  `POST_ONLY` rest good-till-time, expiring with their signature (`core.ORDER_TTL`).

  Raises:
    ValueError: The quantity is zero or not finite, or a limit price is not positive.
  """
  qty = Decimal(str(order['qty']))
  if not qty.is_finite() or not qty:
    raise ValueError('Order quantity must be finite and nonzero')
  if order['type'] == 'MARKET':
    market: MarketOrder = {
      'is_market': True,
      'time_in_force': 'IMMEDIATE_OR_CANCEL',
      'metadata': {'client_order_id': client_order_id},
      'legs': [
        {'instrument': instrument, 'size': abs(qty), 'is_buying_asset': qty > 0}
      ],
    }
    return market
  price = Decimal(str(order['price']))
  if not price.is_finite() or price <= 0:
    raise ValueError('Limit price must be finite and positive')
  limit: LimitOrder = {
    'time_in_force': 'GOOD_TILL_TIME',
    'post_only': order['type'] == 'POST_ONLY',
    'metadata': {'client_order_id': client_order_id},
    'legs': [
      {
        'instrument': instrument,
        'size': abs(qty),
        'limit_price': price,
        'is_buying_asset': qty > 0,
      }
    ],
  }
  return limit


async def place_order(shared: Shared, instrument: str, order: Order) -> OrderResponse:
  """Sign and send a single-leg order; its client order id is the SDK id.

  The caller's `client_order_id` is sent unchanged (GRVT takes integers, and reserves
  `[2^63, 2^64)` for API clients), else a fresh one in that range is used. The reply is
  the order as accepted (`PENDING`, nothing filled yet): a refusal after acceptance,
  such as a post-only order that would cross or a margin check, only shows as a
  `REJECTED` state.

  Raises:
    AuthError: The client has no private key to sign with.
    OrderRejected: The venue refused the order before accepting it.
  """
  shared.require_signer()
  client_order_id = order.get('client_order_id') or random_client_order_id()
  new = new_order(instrument, order, client_order_id)
  try:
    reply = await shared.call(lambda: shared.client.trading.create_order(new))
  except BadRequest as exc:
    if refused(exc):
      raise OrderRejected(*exc.args) from exc
    raise
  return OrderResponse(id=client_order_id, details=reply)


async def cancel_order(shared: Shared, id: str) -> Any:
  """Cancel by client order id. The venue acknowledges any id, known or not."""
  shared.require_session()
  return await shared.call(
    lambda: shared.client.trading.cancel_order({'client_order_id': id})
  )


async def cancel_orders(shared: Shared, ids: Sequence[str]) -> list[Any]:
  """Cancel by client order id with `bulk_orders`, 100 ids per request."""
  shared.require_session()
  batches = [list(ids[i : i + CANCEL_BATCH]) for i in range(0, len(ids), CANCEL_BATCH)]
  acks: list[Any] = []
  for batch in batches:
    acks.append(
      await shared.call(
        lambda: shared.client.trading.bulk_orders({'client_order_i_ds': batch})
      )
    )
  return acks


async def cancel_open_orders(shared: Shared, instrument: str) -> Any:
  """The venue's cancel-all, scoped to the perpetual by kind, base and quote."""
  shared.require_session()
  base, quote = scope(await shared.instrument(instrument))
  return await shared.call(
    lambda: shared.client.trading.cancel_all_orders(
      kind=['PERPETUAL'], base=base, quote=quote
    )
  )


async def query_order(shared: Shared, instrument: str, id: str) -> OrderState | None:
  """Look an order up by client order id; cancelled and filled orders stay queryable.

  An unknown id (`1004`) or an order on another instrument is `None`.
  """
  shared.require_session()
  try:
    o: GrvtOrder = await shared.call(
      lambda: shared.client.trading.order({'client_order_id': id})
    )
  except BadRequest as exc:
    if exc.args and exc.args[0] == NOT_FOUND:
      return None
    raise
  if o['legs'][0]['instrument'] != instrument:
    return None
  return parse_order(o)


async def open_orders(shared: Shared, instrument: str) -> Sequence[OrderState]:
  """The perpetual's open orders."""
  shared.require_session()
  base, quote = scope(await shared.instrument(instrument))
  rows = await shared.call(
    lambda: shared.client.trading.open_orders(
      kind=['PERPETUAL'], base=base, quote=quote
    )
  )
  return [parse_order(o) for o in rows if o['legs'][0]['instrument'] == instrument]
