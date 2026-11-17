"""Order placement, cancellation and lookup.

The SDK order id is the venue's composite order id (`0x` and 48 hex digits), which
`orders.place` returns and every cancel and lookup takes. Placements and cancels are
on-chain transactions the API submits and waits for, so their replies are final.
"""

from decimal import Decimal

from typing_extensions import Any, Awaitable, Callable, Sequence, TypeVar
from typed_risex import BadRequest as ClientBadRequest
from typed_risex.markets.all import MarketInfo
from typed_risex.schemas import LimitOrderRequest
from tribulnation.sdk.core import BadRequest, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, OrderState

from ..core import Shared, wad
from .common import parse_order

T = TypeVar('T')

REFUSED_CODES = frozenset({'InvalidArgument', 'OutOfRange', 'FailedPrecondition'})
"""Codes of a placement the venue refused: the transaction was never sent, or it
reverted (`PlaceOrder reverted: PostOnlyOrderMatched()`, `OrderPriceOutsideMatchBand`),
so nothing rests and nothing filled."""
NOT_OPEN = ('is not open', 'already filled or cancelled')
"""How a cancel of an order that no longer rests is refused (`InvalidArgument`):
`order <n> is not open (status: 3)`, or `order is already filled or cancelled` for an
id the venue never had (testnet, 2026-11-17)."""
IOC = 3
"""The venue's immediate-or-cancel `time_in_force`."""


def client_code(exc: BadRequest) -> tuple[str, str] | None:
  """The venue's error code and message behind a translated `BadRequest`, if the venue
  answered with one."""
  cause = exc.__cause__
  if not isinstance(cause, ClientBadRequest) or len(cause.args) < 2:
    return None
  code, message = cause.args[0], cause.args[1]
  if not isinstance(code, str) or not isinstance(message, str):
    return None
  return code, message


async def submit(shared: Shared, send: Callable[[], Awaitable[T]]) -> T:
  """Send a placement, raising `OrderRejected` when the venue refused it."""
  try:
    return await shared.call(send)
  except BadRequest as exc:
    answer = client_code(exc)
    if answer is not None and answer[0] in REFUSED_CODES:
      raise OrderRejected(*exc.args) from exc
    raise


def whole(value: Decimal, step: Decimal, *, what: str, name: str) -> int:
  """`value` as a whole number of `step`s.

  Raises:
    ValueError: `value` is not a multiple of `step`.
  """
  units = value / step
  if units != units.to_integral_value():
    raise ValueError(f'RISEx {name}: {what} {value} is not a multiple of {step}')
  return int(units)


def order_request(market: MarketInfo, order: Order) -> LimitOrderRequest:
  """The venue request for an SDK order, checked before signing.

  `LIMIT` is a good-till-cancelled limit order, `POST_ONLY` the same with `post_only`,
  and `MARKET` an immediate-or-cancel limit at `price`. Not the venue's market order
  (`order_type 0`): on testnet one priced 3% under the bid filled above the bid, so its
  price does not bound the fill, while the IOC limit at that price did not fill.

  Raises:
    ValueError: Zero size, a non-positive price, an off-grid price or size, or a client
      order id that is not a non-negative decimal integer.
  """
  config = market['config']
  name = config['name']
  qty, price = Decimal(order['qty']), Decimal(order['price'])
  if qty == 0:
    raise ValueError(f'RISEx {name}: an order needs a non-zero qty')
  if price <= 0:
    raise ValueError(f'RISEx {name}: an order needs a positive price, not {price}')
  request: LimitOrderRequest = {
    'market_id': market['market_id'],
    'order_type': 1,
    'side': 0 if qty > 0 else 1,
    'size_steps': whole(abs(qty), config['step_size'], what='qty', name=name),
    'price_ticks': whole(price, config['step_price'], what='price', name=name),
  }
  if order['type'] == 'POST_ONLY':
    request['post_only'] = True
  elif order['type'] == 'MARKET':
    request['time_in_force'] = IOC
  client_id = order.get('client_order_id')
  if client_id is not None:
    if not client_id.isdigit():
      raise ValueError(
        f'RISEx client order ids are non-negative integers, not {client_id!r}'
      )
    request['client_order_id'] = int(client_id)
  return request


async def place_order(
  shared: Shared, market: MarketInfo, order: Order
) -> OrderResponse:
  """Sign and send one order; see `order_request` for the mapping.

  The venue reports what filled for immediate-or-cancel orders only (`MARKET`), so
  `filled_qty` is `None` for resting ones.

  Raises:
    AuthError: The client has no signer key.
    ValueError: See `order_request`.
    OrderRejected: The venue refused the order: nothing rests.
  """
  request = order_request(market, order)
  shared.require_signer()
  placed = await submit(shared, lambda: shared.client.orders.place(request))
  filled = placed['filled_quantity']
  return OrderResponse(
    id=placed['order_id'],
    details=placed,
    filled_qty=None if filled == '' else wad(filled),
  )


async def cancel_order(shared: Shared, market_id: int, id: str) -> Any:
  """Cancel one order; the reply is the mined transaction.

  Raises:
    AuthError: The client has no signer key.
    OrderNotFound: The order no longer rests (filled, cancelled or unknown).
  """
  shared.require_signer()
  try:
    return await shared.call(
      lambda: shared.client.orders.cancel(market_id, order_id=id)
    )
  except BadRequest as exc:
    answer = client_code(exc)
    if answer is not None and answer[0] == 'InvalidArgument':
      if any(text in answer[1] for text in NOT_OPEN):
        raise OrderNotFound(*exc.args) from exc
    raise


async def cancel_open_orders(shared: Shared, market_id: int) -> Any:
  """Cancel every resting order of the account in the market, in one transaction.

  Raises:
    AuthError: The client has no signer key.
  """
  shared.require_signer()
  return await shared.call(lambda: shared.client.orders.cancel_all(market_id))


async def query_order(shared: Shared, market_id: int, id: str) -> OrderState | None:
  """Look an order up by id, open or closed; `None` when the venue does not know it
  (`NotFound`) or it belongs to another market."""
  try:
    found = await shared.call(lambda: shared.client.orders.get(id, market_id=market_id))
  except BadRequest as exc:
    answer = client_code(exc)
    if answer is not None and answer[0] == 'NotFound':
      return None
    raise
  o = found['order']
  if o['market_id'] != market_id:
    return None
  return parse_order(o)


async def open_orders(shared: Shared, market_id: int) -> Sequence[OrderState]:
  """The account's resting orders in the market.

  `orders.open` (on-chain state, every resting order in one reply) says which rest; it
  carries no fill progress, so each order's size and fills come from the indexer
  (`orders.history`, open status), else from its own `orders.get`.
  """
  account = shared.require_account()
  resting = await shared.call(
    lambda: shared.client.orders.open(account=account, market_id=market_id)
  )
  ids = [o['order_id'] for o in resting['orders'] if o['market_id'] == market_id]
  if not ids:
    return []
  pages = shared.client.orders.history_paged(
    account=account,
    market_id=market_id,
    statuses=['ORDER_STATUS_OPEN'],
    limit=1000,
  ).via(shared.call)
  indexed: dict[str, OrderState] = {}
  async for page in pages:
    for o in page:
      indexed[o['id']] = parse_order(o)
  states: list[OrderState] = []
  for id in ids:
    state = indexed.get(id) or await query_order(shared, market_id, id)
    if state is not None:
      states.append(state)
  return states
