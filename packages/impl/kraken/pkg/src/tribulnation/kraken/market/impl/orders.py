"""Spot orders over REST: open orders, order state, and placing, amending and
cancelling limit orders."""

from typing_extensions import TYPE_CHECKING, Any, Sequence
from decimal import Decimal

from tribulnation.sdk.core import ApiError, BadRequest, OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings
from tribulnation.sdk.market import SpotMarket as BaseSpotMarket
from tribulnation.sdk.util import to_decimal

from typed_kraken.spot.account import open_orders as listing
from typed_kraken.spot.account import query_orders as queried
from typed_kraken.spot.trading.add_order import AddOrderLimit

from .perp_account import KrakenSettings, order_type
from .perp_orders import venue_settings

if TYPE_CHECKING:
  from .mixin import MarketMixin
  from ..spot_market import SpotMarket

AMBIGUOUS = ('Internal error', 'Unavailable', 'Busy', 'Timeout')
"""Error descriptions that do not say whether an order reached the book."""
GONE = ('Unknown order', 'Invalid order')
"""Error descriptions of an order id Kraken no longer (or never) knew."""


def errors_of(e: Exception) -> list[str]:
  """Kraken's `error` array carried by a translated exception, `<Category>:<Description>`."""
  match e.args:
    case ([*errors],):
      return [str(m) for m in errors]
    case _:
      return []


def says(e: Exception, descriptions: Sequence[str]) -> bool:
  """Whether Kraken's primary error names one of `descriptions`."""
  errors = errors_of(e)
  return bool(errors) and any(s in errors[0] for s in descriptions)


def rejection(e: ApiError) -> ApiError:
  """The error placing an order raised, as `OrderRejected` where Kraken's answer is final.

  An `EOrder` error (insufficient funds, minimums, post-only, market mode, ...) and a
  bad request (invalid arguments, tick size) mean nothing was placed. Service errors,
  internal errors and rate limits are returned unchanged: they are ambiguous, or say
  something other than a refusal of this order.
  """
  errors = errors_of(e)
  final = (
    bool(errors)
    and not says(e, AMBIGUOUS)
    and (isinstance(e, BadRequest) or errors[0].startswith('EOrder:'))
  )
  return OrderRejected(*e.args) if final else e


def decimal_text(value: Decimal) -> str:
  """`value` in plain notation without trailing zeros, as Kraken's form fields take it."""
  return format(value.normalize(), 'f')


def parse_order(
  txid: str, order: listing.OpenOrder | queried.OpenOrder | queried.ClosedOrder
) -> OrderState:
  """Map one open or queried order onto an `OrderState`.

  `pending` is an order awaiting book entry: not yet resting, but not finished
  with either, so it counts as active alongside `open`.
  """
  descr = order.get('descr') or {}
  sign = 1 if descr.get('type') == 'buy' else -1
  return OrderState(
    id=txid,
    price=descr.get('price', Decimal(0)),
    qty=sign * order.get('vol', Decimal(0)),
    filled_qty=sign * order.get('vol_exec', Decimal(0)),
    active=order.get('status') in ('pending', 'open'),
    details=order,
  )


async def open_orders(self: 'MarketMixin') -> Sequence[OrderState]:
  """Fetch the market's currently open orders.

  `OpenOrders` is account-wide and unpaged, so the answer is filtered here on the
  order description's pair, which Kraken spells as the altname.
  """
  raw = await self.call_kraken(self.client.spot.account.open_orders)
  return [
    parse_order(txid, order)
    for txid, order in (raw.get('open') or {}).items()
    if (order.get('descr') or {}).get('pair') == self.altname
  ]


async def query_order(self: 'MarketMixin', id: str) -> OrderState | None:
  """Fetch one order by txid, open or closed (`QueryOrders`); `None` when Kraken does
  not know it."""
  try:
    rows = await self.call_kraken(lambda: self.client.spot.account.query_orders(id))
  except ApiError as e:
    if not says(e, GONE):
      raise
  else:
    if (row := rows.get(id)) is not None:
      return parse_order(id, row)


def add_order_request(
  self: 'MarketMixin', order: Order, venue: KrakenSettings
) -> AddOrderLimit:
  """The `AddOrder` request placing `order` as a limit order.

  `LIMIT` rests (GTC) unless `venue['time_in_force']` says `post` or `ioc`;
  `POST_ONLY` adds the `post` flag; `MARKET` is an IOC limit at `price`, which bounds
  it. Fees are always charged in the quote asset (`fciq`), so the base a fill moves
  is exactly its quantity.

  Raises:
    ValueError: `reduce_only` was asked for, which a Spot order cannot honour.
  """
  if venue.get('reduce_only'):
    raise ValueError(f'reduce_only is not supported on Kraken Spot [{self.altname}]')
  qty = to_decimal(order['qty'])
  kind = order_type(order, venue)
  request: AddOrderLimit = {
    'pair': self.altname,
    'type': 'buy' if qty > 0 else 'sell',
    'ordertype': 'limit',
    'volume': decimal_text(abs(qty)),
    'price': decimal_text(to_decimal(order['price'])),
    'oflags': 'post,fciq' if kind == 'post' else 'fciq',
  }
  if kind == 'ioc':
    request['timeinforce'] = 'IOC'
  if (cl_ord_id := order.get('client_order_id')) is not None:
    request['cl_ord_id'] = cl_ord_id
  return request


async def place_order(
  self: 'MarketMixin', order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Place one limit order with `AddOrder`; see `add_order_request`.

  `AddOrder` answers the txid only, so `filled_qty` is `None`: read fills off
  `trades_stream`, or `query_order` once an IOC is done.

  Raises:
    OrderRejected: Kraken refused it (`EOrder:*`, or a bad request).
  """
  request = add_order_request(self, order, venue_settings(settings))
  try:
    result = await self.call_kraken(lambda: self.client.spot.trading.add_order(request))
  except ApiError as e:
    if (error := rejection(e)) is e:
      raise
    raise error from e
  finally:
    self.shared.forget_balances()
  match result.get('txid'):
    case [txid, *_]:
      return OrderResponse(id=txid, details=result)
    case _:
      raise ApiError('Kraken AddOrder answered no txid', result)


async def replace_order(
  self: 'SpotMarket', id: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Amend `id` in place (`AmendOrder`) to `order`'s price and resting size.

  The order keeps its txid, and its queue priority where Kraken can keep it. Kraken
  amends the order's total quantity, so the new total is what `id` already filled
  plus `|qty|`, read fresh with `QueryOrders`. An order already gone is placed afresh;
  one on the other side is cancelled and placed, since an amend cannot change the
  side.

  Raises:
    OrderRejected: The order was gone and the new one was refused.
    ApiError: Kraken refused the amend; `id` still rests as it was.
  """
  qty = to_decimal(order['qty'])
  state = await query_order(self, id)
  if state is None or not state.active:
    return await place_order(self, order, settings=settings)
  elif (state.qty > 0) != (qty > 0):
    return await BaseSpotMarket.replace_order(self, id, order, settings=settings)
  else:
    total = abs(state.filled_qty) + abs(qty)
    try:
      result = await self.call_kraken(
        lambda: self.client.spot.trading.amend_order(
          txid=id,
          order_qty=decimal_text(total),
          limit_price=decimal_text(to_decimal(order['price'])),
          post_only=True if order['type'] == 'POST_ONLY' else None,
        )
      )
    except ApiError as e:
      if says(e, GONE):
        return await place_order(self, order, settings=settings)
      raise
    finally:
      self.shared.forget_balances()
    return OrderResponse(id=id, details=result)


async def cancel_order(self: 'MarketMixin', id: str) -> Any:
  """Cancel one order by txid (`CancelOrder`).

  Raises:
    OrderNotFound: Kraken does not know the order, or it no longer rests.
  """
  try:
    result = await self.call_kraken(
      lambda: self.client.spot.trading.cancel_order(txid=id)
    )
  except ApiError as e:
    if says(e, GONE):
      raise OrderNotFound(f'Kraken order {id} not found', *e.args) from e
    raise
  finally:
    self.shared.forget_balances()
  if result.get('count') == 0 and not result.get('pending'):
    raise OrderNotFound(f'Kraken order {id} no longer rests', result)
  return result
