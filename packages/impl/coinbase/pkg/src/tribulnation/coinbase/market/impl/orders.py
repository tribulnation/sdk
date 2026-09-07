"""Order placement, cancellation and open-order reads for one product."""

from typing_extensions import Sequence
from decimal import Decimal
import uuid

from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings

from typed_coinbase.schemas import (
  Order as PlacedOrder,
  LimitLimitGtcConfiguration,
  MarketMarketIocConfiguration,
  OrderConfiguration,
)

from tribulnation.coinbase.core import wrap_exceptions
from .mixin import MarketMixin

ACTIVE_STATUSES = ('OPEN', 'PENDING', 'QUEUED')


def parse_order(order: PlacedOrder) -> OrderState:
  """Map one Advanced Trade order onto an `OrderState`.

  `Order` carries no top-level original size -- it lives nested per order type inside
  `order_configuration` -- so the total is backed out of `filled_size` and
  `completion_percentage`, falling back to the filled size in the one case that ratio
  cannot cover: nothing filled yet.
  """
  sign = 1 if order['side'] == 'BUY' else -1
  filled = order.get('filled_size') or Decimal(0)
  completion = order['completion_percentage']
  qty = filled / (completion / 100) if completion else filled
  return OrderState(
    id=order['order_id'],
    price=order['average_filled_price'],
    qty=sign * qty,
    filled_qty=sign * filled,
    active=order['status'] in ACTIVE_STATUSES,
    details=order,
  )


async def open_orders(self: MarketMixin) -> Sequence[OrderState]:
  """Fetch the product's currently open orders, page by page."""
  paging = self.app.advanced_trade.http.orders.historical.batch_paged(
    product_ids=[self.product_id], order_status=['OPEN']
  )
  return [parse_order(order) for order in await paging.via(self.call_app)]


def order_configuration(order: Order) -> OrderConfiguration:
  """Map an SDK order onto the Advanced Trade order configuration it asks for."""
  base_size = abs(Decimal(order['qty']))
  price = Decimal(order['price'])
  if order['type'] == 'MARKET':
    market: MarketMarketIocConfiguration = {
      'market_market_ioc': {'base_size': base_size}
    }
    return market
  limit: LimitLimitGtcConfiguration = {
    'limit_limit_gtc': {'base_size': base_size, 'limit_price': price}
  }
  if order['type'] == 'POST_ONLY':
    limit['limit_limit_gtc']['post_only'] = True
  return limit


@wrap_exceptions
async def place_order(
  self: MarketMixin, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Place an order on the product."""
  response = await self.app.advanced_trade.http.orders.create(
    client_order_id=str(uuid.uuid4()),
    product_id=self.product_id,
    side='BUY' if Decimal(order['qty']) > 0 else 'SELL',
    order_configuration=order_configuration(order),
  )
  # `create` returns a `CreateOrderSuccess | CreateOrderFailure` union discriminated by
  # the literal `success` field; compare against it explicitly, as plain truthiness
  # doesn't narrow a `TypedDict` union.
  if response['success'] is False:
    raise ApiError(f'Coinbase rejected the order: {response["error_response"]}')
  return OrderResponse(id=response['success_response']['order_id'], details=response)


@wrap_exceptions
async def cancel_order(self: MarketMixin, id: str, *, settings: Settings = {}):
  """Cancel one order on the product."""
  return await self.app.advanced_trade.http.orders.batch_cancel([id])
