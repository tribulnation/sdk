"""Order placement, cancellation and lookup, shared by perp and spot markets.

The SDK order id is the `client_order_index` assigned at placement: a create-order
transaction only returns its hash (the venue assigns `order_index` on execution), and
the venue accepts the client index wherever it takes an `order_index`.
"""

from decimal import Decimal

from typing_extensions import Any, Sequence
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings

from ..core import Shared
from .common import parse_order


async def place_order(
  shared: Shared, market_id: int, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Sign and send a create-order transaction.

  `LIMIT` rests good-till-time (the venue's 28-day default expiry), `POST_ONLY` is
  rejected rather than taking liquidity, and `MARKET` is the venue's market order with
  `price` as the worst acceptable price. Off-grid prices and sizes raise before signing.
  Acceptance is not execution: a sequencer rejection shows as a `canceled-*` status.
  """
  lighter = settings.get('lighter', {})
  scaler = await shared.scaler(market_id)
  qty = Decimal(order['qty'])
  client_index = shared.client_indexes.next()
  base_amount = scaler.size(abs(qty))
  price = scaler.price(Decimal(order['price']))
  reduce_only = lighter.get('reduce_only', False)
  if order['type'] == 'MARKET':
    response = await shared.call(
      lambda: shared.client.tx.create_order(
        {
          'order_type': 'market',
          'market_index': market_id,
          'client_order_index': client_index,
          'base_amount': base_amount,
          'is_ask': qty < 0,
          'price': price,
          'reduce_only': reduce_only,
        }
      )
    )
  else:
    response = await shared.call(
      lambda: shared.client.tx.create_order(
        {
          'order_type': 'limit',
          'market_index': market_id,
          'client_order_index': client_index,
          'base_amount': base_amount,
          'is_ask': qty < 0,
          'price': price,
          'time_in_force': 'post-only'
          if order['type'] == 'POST_ONLY'
          else 'good-till-time',
          'reduce_only': reduce_only,
        }
      )
    )
  return OrderResponse(id=str(client_index), details=response)


def client_index(id: str) -> int:
  """An SDK order id as the venue's client order index."""
  try:
    return int(id)
  except ValueError:
    raise ValueError(f'Lighter order ids are client order indexes: {id!r}') from None


async def cancel_order(shared: Shared, market_id: int, id: str) -> Any:
  """Cancel by client order index."""
  index = client_index(id)
  return await shared.call(
    lambda: shared.client.tx.cancel_order(market_index=market_id, order_index=index)
  )


async def query_order(shared: Shared, market_id: int, id: str) -> OrderState | None:
  """Look an order up by client index: active orders, and inactive ones of the last 24h.

  A cancelled order leaves the active set seconds before it is indexed as inactive; in
  that window, and after 24h, it is not found.
  """
  index, account = client_index(id), shared.account_index
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
  account = shared.account_index
  orders = await shared.call(
    lambda: shared.client.api.account.orders.active(
      account_index=account, market_id=market_id
    )
  )
  return [parse_order(o) for o in orders['orders']]
