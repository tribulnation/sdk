"""Order entry on a Kraken perpetual: send, batch, edit and cancel."""

from typing_extensions import TYPE_CHECKING, Any, Literal, Sequence, cast

from tribulnation.sdk.core import OrderNotFound, OrderRejected
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings
from tribulnation.sdk.util import to_decimal
from typed_kraken.futures_trading.types import BatchInstruction

from .perp_account import (
  IMMEDIATE,
  KrakenSettings,
  cancel_outcome,
  edit_outcome,
  open_order_state,
  order_response,
  order_type,
)

if TYPE_CHECKING:
  from ..perp_market import PerpMarket


def venue_settings(settings: Settings) -> KrakenSettings:
  """This venue's entry of `settings`."""
  return cast(KrakenSettings, settings.get('kraken') or {})


def send_instruction(
  market: 'PerpMarket', order: Order, venue: KrakenSettings, tag: str
) -> BatchInstruction:
  """The batch instruction placing `order`."""
  qty = to_decimal(order['qty'])
  instruction: BatchInstruction = {
    'order': 'send',
    'order_tag': tag,
    'orderType': order_type(order, venue),
    'symbol': market.symbol,
    'side': 'buy' if qty > 0 else 'sell',
    'size': abs(qty),
    'limitPrice': to_decimal(order['price']),
  }
  if (cli_ord_id := order.get('client_order_id')) is not None:
    instruction['cliOrdId'] = cli_ord_id
  if (reduce_only := venue.get('reduce_only')) is not None:
    instruction['reduceOnly'] = reduce_only
  return instruction


async def place_order(
  market: 'PerpMarket', order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Place a `LIMIT` (`lmt`), `POST_ONLY` (`post`) or `MARKET` (`ioc` at `price`).

  `filled_qty` is what filled on arrival; final for IOC and `MARKET` orders.

  Raises:
    OrderRejected: Kraken did not place it: a post-only that would cross, an IOC
      with nothing to fill, insufficient funds, an invalid price or size, ...
  """
  venue = venue_settings(settings)
  kind = order_type(order, venue)
  qty = to_decimal(order['qty'])
  result = await market.call_kraken(
    lambda: market.perp.client.trading.send_order(
      order_type=kind,
      symbol=market.symbol,
      side='buy' if qty > 0 else 'sell',
      size=abs(qty),
      limit_price=to_decimal(order['price']),
      cli_ord_id=order.get('client_order_id'),
      reduce_only=venue.get('reduce_only'),
    )
  )
  market.perp.forget_account()
  response = order_response(result['sendStatus'], immediate=kind in IMMEDIATE)
  market.perp.remember(
    response.id, symbol=market.symbol, side='buy' if qty > 0 else 'sell'
  )
  return response


async def place_orders(
  market: 'PerpMarket', orders: Sequence[Order], *, settings: Settings = {}
) -> Sequence[OrderResponse | Exception]:
  """Place several orders in one `batchorder`; one result per order.

  A failed request fails every order with its error (each may have been placed).
  """
  if not orders:
    return []
  venue = venue_settings(settings)
  instructions = [
    send_instruction(market, order, venue, str(i)) for i, order in enumerate(orders)
  ]
  try:
    result = await market.call_kraken(
      lambda: market.perp.client.trading.batch_order(instructions)
    )
  except Exception as e:
    return [e] * len(orders)
  market.perp.forget_account()
  statuses = {s.get('order_tag'): s for s in result['batchStatus']}

  def outcome(i: int, order: Order) -> OrderResponse | Exception:
    """The `i`-th order's response, or its error."""
    try:
      immediate = order_type(order, venue) in IMMEDIATE
      response = order_response(statuses[str(i)], immediate=immediate)
    except Exception as e:
      return e
    side = 'buy' if to_decimal(order['qty']) > 0 else 'sell'
    market.perp.remember(response.id, symbol=market.symbol, side=side)
    return response

  return [outcome(i, order) for i, order in enumerate(orders)]


async def order_side(market: 'PerpMarket', id: str) -> Literal['buy', 'sell']:
  """The side of resting order `id` of this market.

  Read from the orders this client placed or listed, so no request is made for
  them; any other is asked of Kraken (`orders/status`) once.

  Raises:
    OrderNotFound: `id` is not a resting order of this market.
  """
  if (known := market.perp.orders.get(id)) is not None and market.owns(known[0]):
    return known[1]
  state = await market.query_order(id)
  if state is not None and state.active:
    side = 'buy' if state.qty > 0 else 'sell'
    market.perp.remember(id, symbol=market.symbol, side=side)
    return side
  else:
    raise OrderNotFound(f'Kraken Futures order {id} does not rest in {market.symbol}')


async def replace_order(
  market: 'PerpMarket', id: str, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Edit `id` in place (`editorder`) to `order`'s price and size, the size to rest
  from now on (Kraken's default `RELATIVE` quantity mode).

  The order keeps its ID. Nothing is ever placed for an order that
  no longer rests. An edit can't change the side, so a replacement on the other
  side cancels `id`, then places `order`.

  Raises:
    OrderNotFound: `id` no longer rests (filled, cancelled or unknown); nothing
      was placed.
    OrderRejected: A post-only edit would have crossed: Kraken cancelled the order.
    ApiError: Kraken refused the edit (`invalidSize`, `invalidPrice`,
      `insufficientAvailableFunds`, ...); the order still rests as it was.
  """
  qty = to_decimal(order['qty'])
  if await order_side(market, id) != ('buy' if qty > 0 else 'sell'):
    await cancel_order(market, id, settings=settings)
    return await place_order(market, order, settings=settings)
  result = await market.call_kraken(
    lambda: market.perp.client.trading.edit_order(
      order_id=id, size=abs(qty), limit_price=to_decimal(order['price'])
    )
  )
  market.perp.forget_account()
  try:
    return edit_outcome(result['editStatus'], id)
  except (OrderNotFound, OrderRejected):
    market.perp.orders.pop(id, None)
    raise


async def open_orders(market: 'PerpMarket') -> Sequence[OrderState]:
  """This market's open orders, whose sides are kept for later edits."""
  result = await market.call_kraken(market.perp.client.trading.open_orders)
  rows = [row for row in result['openOrders'] if market.owns(row['symbol'])]
  for row in rows:
    market.perp.remember(row['order_id'], symbol=market.symbol, side=row['side'])
  return [open_order_state(row) for row in rows]


async def cancel_order(
  market: 'PerpMarket', id: str, *, settings: Settings = {}
) -> Any:
  """Cancel one order.

  Raises:
    OrderNotFound: The order no longer rests (`notFound`, `filled`).
  """
  result = await market.call_kraken(
    lambda: market.perp.client.trading.cancel_order(order_id=id)
  )
  market.perp.forget_account()
  outcome = cancel_outcome(result['cancelStatus'], id)
  if isinstance(outcome, Exception):
    raise outcome
  return outcome


async def cancel_orders(
  market: 'PerpMarket', ids: Sequence[str], *, settings: Settings = {}
) -> Sequence[str | Exception]:
  """Cancel in one `batchorder`: per order, `cancelled` or its error."""
  if not ids:
    return []
  result = await market.call_kraken(
    lambda: market.perp.client.trading.batch_order(
      [{'order': 'cancel', 'order_id': id} for id in ids]
    )
  )
  market.perp.forget_account()
  statuses = {s.get('order_id'): s for s in result['batchStatus']}
  return [
    cancel_outcome(statuses[id], id)
    if id in statuses
    else OrderNotFound(f'Kraken Futures answered no status for {id}')
    for id in ids
  ]


async def cancel_open_orders(market: 'PerpMarket', *, settings: Settings = {}) -> Any:
  """Cancel every open order of this market (`cancelallorders` by symbol)."""
  result = await market.call_kraken(
    lambda: market.perp.client.trading.cancel_all_orders(market.symbol)
  )
  market.perp.forget_account()
  return result
