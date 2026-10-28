"""Order placement, cancellation and lookup.

The SDK order id is Extended's order `id` (a 64-bit integer, as a decimal string): the
venue returns it on acceptance and every cancel and lookup takes it.
"""

from datetime import datetime, timezone
from decimal import Decimal
import secrets

from typing_extensions import Any, Awaitable, Callable, Literal, Sequence
from typed_extended.core.exc import BadRequest as ClientBadRequest
from typed_extended.info.markets import Market as MarketRow
from typed_extended.orders.create import LimitOrderRequest, MarketOrderRequest
from typed_extended.orders.create_rfq import RfqLimitOrderRequest, RfqMarketOrderRequest
from typed_extended.orders.schemas import PlacedOrder
from tribulnation.sdk.core import BadRequest, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, OrderState

from ..core import EXPIRY_MARGIN, ORDER_LIFETIME, Settings, Shared
from .common import parse_order

DUPLICATE_ORDER = 1134
"""`DuplicateOrder`: the same signed order (the same settlement nonce) was already
submitted, so the refusal does not say nothing rests: the earlier submission may have
gone through. A reused client id alone is not refused (testnet, 2026-10-22)."""
UNHANDLED_ERROR = 1006
"""`UnhandledError`: the venue's catch-all, which says nothing certain about the order."""
UNCERTAIN_CODES = frozenset({DUPLICATE_ORDER, UNHANDLED_ERROR})
"""Coded refusals that do not establish the order is dead."""


def random_client_order_id() -> str:
  """A fresh client order id: 32 random hex digits (ADR 0029)."""
  return secrets.token_hex(16)


def refused(exc: BadRequest) -> bool:
  """Whether a submission `BadRequest` is the venue refusing the order outright.

  `typed_extended` raises `BadRequest(code, message, payload)` for an error envelope
  the venue answered (a `4xx`, or a `2xx` with `status: ERROR`) carrying an application
  code, and `BadRequest(status, payload)` for a code-less one. Only the coded form, and
  not `1134` DuplicateOrder or `1006` UnhandledError, makes the refusal certain. `5xx`,
  `401`/`403` and `429` raise other classes and never reach here.
  """
  cause = exc.__cause__
  if not isinstance(cause, ClientBadRequest) or len(cause.args) != 3:
    return False
  code, _, payload = cause.args
  return isinstance(payload, dict) and code not in UNCERTAIN_CODES


async def submit(
  shared: Shared, send: Callable[[], Awaitable[PlacedOrder]]
) -> PlacedOrder:
  """Send a create-order request, raising `OrderRejected` for a certain refusal."""
  try:
    return await shared.call(send)
  except BadRequest as exc:
    if refused(exc):
      raise OrderRejected(*exc.args) from exc
    raise


def on_grid(value: Decimal, step: Decimal) -> bool:
  """Whether `value` is a whole number of `step`s."""
  return value % step == 0


def check_order(row: MarketRow, qty: Decimal, price: Decimal):
  """Refuse what the venue would refuse, before signing: an off-grid price or size.

  Raises:
    ValueError: The size is zero, the price is not positive, or either is off-grid.
  """
  config = row['tradingConfig']
  name = row['name']
  if qty == 0:
    raise ValueError(f'Extended {name}: an order needs a non-zero qty')
  if price <= 0:
    raise ValueError(f'Extended {name}: an order needs a positive price, not {price}')
  if not on_grid(price, config['minPriceChange']):
    raise ValueError(
      f'Extended {name}: price {price} is not a multiple of the tick '
      f'{config["minPriceChange"]}'
    )
  if not on_grid(abs(qty), config['minOrderSizeChange']):
    raise ValueError(
      f'Extended {name}: qty {qty} is not a multiple of the step '
      f'{config["minOrderSizeChange"]}'
    )


async def place_order(
  shared: Shared, row: MarketRow, order: Order, settings: Settings = {}
) -> OrderResponse:
  """Sign and send one order; an RFQ market's go through `create_rfq`.

  `LIMIT` rests good-till-time until the network's longest expiry (90 days on mainnet,
  28 on testnet, less a minute); `POST_ONLY` adds `postOnly`, and an RFQ market refuses
  it; `MARKET` is the venue's market order (immediate-or-cancel) bounded by `price`.
  With the `time_in_force: 'IOC'` setting a `LIMIT` is immediate-or-cancel instead, with
  the client's default expiry (an hour), as a `MARKET` order carries.
  Self-trade protection is `ACCOUNT`. The fee cap is the account's maker rate for
  post-only orders and its taker rate otherwise, and `client_order_id` is sent as the
  order's `id` (its `externalId`; the order hash when omitted). The venue does not keep
  client ids unique: reusing one places a second order.

  Acceptance is asynchronous: the response carries the order id and `filled_qty` stays
  `None`. A later refusal by the matching engine shows as `REJECTED` in `query_order`.

  Raises:
    AuthError: The client cannot sign (no Stark private key).
    ValueError: Zero size, non-positive or off-grid price or size, `POST_ONLY` on an
      RFQ market, or `time_in_force` set on an order other than `LIMIT`.
    OrderRejected: The venue refused the order with an error code (other than `1134`
      DuplicateOrder and `1006` UnhandledError): nothing rests. Observed: `1140`, the
      order's cost exceeds the available balance, and `1120`, a size below the
      minimum.
  """
  market, rfq = row['name'], row['isRfq']
  time_in_force = settings.get('time_in_force')
  if time_in_force is not None and order['type'] != 'LIMIT':
    raise ValueError(
      f'Extended time_in_force applies to LIMIT orders only, not {order["type"]}'
    )
  qty = Decimal(order['qty'])
  price = Decimal(order['price'])
  check_order(row, qty, price)
  if rfq and order['type'] == 'POST_ONLY':
    raise ValueError(
      f'Extended {market} is an RFQ market: post-only orders are refused'
    )
  shared.require_signer()
  side: Literal['BUY', 'SELL'] = 'BUY' if qty > 0 else 'SELL'
  client_id = order.get('client_order_id')
  orders = shared.client.orders
  if order['type'] == 'MARKET':
    request: MarketOrderRequest = {
      'type': 'MARKET',
      'market': market,
      'side': side,
      'qty': abs(qty),
      'price': price,
      'timeInForce': 'IOC',
      'selfTradeProtectionLevel': 'ACCOUNT',
    }
    if client_id is not None:
      request['id'] = client_id
    if rfq:
      rfq_market: RfqMarketOrderRequest = {**request}
      placed = await submit(shared, lambda: orders.create_rfq(rfq_market))
    else:
      placed = await submit(shared, lambda: orders.create(request))
  else:
    expiry = datetime.now(timezone.utc) + ORDER_LIFETIME[shared.network] - EXPIRY_MARGIN
    if rfq:
      rfq_limit: RfqLimitOrderRequest = {
        'type': 'LIMIT',
        'market': market,
        'side': side,
        'qty': abs(qty),
        'price': price,
        'timeInForce': time_in_force or 'GTT',
        'selfTradeProtectionLevel': 'ACCOUNT',
      }
      if time_in_force is None:
        rfq_limit['expiryEpochMillis'] = expiry
      if client_id is not None:
        rfq_limit['id'] = client_id
      placed = await submit(shared, lambda: orders.create_rfq(rfq_limit))
    else:
      limit: LimitOrderRequest = {
        'type': 'LIMIT',
        'market': market,
        'side': side,
        'qty': abs(qty),
        'price': price,
        'timeInForce': time_in_force or 'GTT',
        'selfTradeProtectionLevel': 'ACCOUNT',
        'postOnly': order['type'] == 'POST_ONLY',
      }
      if time_in_force is None:
        limit['expiryEpochMillis'] = expiry
      if client_id is not None:
        limit['id'] = client_id
      placed = await submit(shared, lambda: orders.create(limit))
  return OrderResponse(id=str(placed['id']), details=placed)


def order_id(id: str) -> int:
  """An SDK order id as Extended's numeric order id.

  Raises:
    ValueError: The id is not a decimal integer.
  """
  try:
    return int(id)
  except ValueError:
    raise ValueError(f'Extended order ids are integers: {id!r}') from None


async def cancel_order(shared: Shared, id: str) -> Any:
  """Cancel by Extended id; the venue only acknowledges the request."""
  index = order_id(id)
  return await shared.call(lambda: shared.client.orders.cancel(index))


async def cancel_orders(shared: Shared, ids: Sequence[str]) -> Any:
  """Cancel several orders by Extended id in one mass-cancel request; none sends none."""
  indexes = [order_id(id) for id in ids]
  if not indexes:
    return None
  return await shared.call(lambda: shared.client.orders.mass_cancel(indexes))


async def query_order(shared: Shared, market: str, id: str) -> OrderState | None:
  """Look an order of the sub-account up by Extended id, open or closed.

  `None` when the venue does not know the id, or the order belongs to another market.
  """
  index = order_id(id)
  o = await shared.call(lambda: shared.client.account.order(index))
  if o is None or o['market'] != market:
    return None
  return parse_order(o)


async def open_orders(shared: Shared, market: str) -> Sequence[OrderState]:
  """The market's open `LIMIT` orders, the only kind `place_order` leaves resting.

  Conditional, TP/SL and TWAP orders are left out, and so left alone by
  `cancel_open_orders`.
  """
  rows = await shared.call(
    lambda: shared.client.account.open_orders([market], type='LIMIT')
  )
  return [parse_order(o) for o in rows]


async def cancel_open_orders(shared: Shared, market: str) -> Any:
  """Cancel exactly what `open_orders` lists, in one mass-cancel request.

  The venue's market-scoped cancel-all would also cancel conditional, TP/SL and TWAP
  orders, which `open_orders` does not list. An order placed after the listing is not
  cancelled.
  """
  listed = await open_orders(shared, market)
  return await cancel_orders(shared, [o.id for o in listed])
