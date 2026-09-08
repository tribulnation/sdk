"""Order placement, cancellation and lookup, over `v1/trading/order`."""

from typing_extensions import TYPE_CHECKING, Sequence
from decimal import Decimal

from tribulnation.sdk.core import ValidationError
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings

from typed_bit2me.schemas import OrderResponse as Bit2MeOrder, OrderSide
from typed_bit2me.v1.trading.orders.create import (
  LimitOrderRequest,
  MarketOrderRequest,
  Request as OrderRequest,
)

if TYPE_CHECKING:
  from .mixin import MarketMixin

ORDERS_PAGE = 100
"""Orders per page. `v1/trading/order` caps a page at 100 and reports no total, so
the walk stops on the first short page."""


def parse_order(order: Bit2MeOrder) -> OrderState:
  """Map one Bit2Me order onto an `OrderState`."""
  id = order.get('id')
  if id is None:
    raise ValidationError('Bit2Me order is missing its id')
  sign = 1 if order.get('side') == 'buy' else -1
  price = order.get('price')
  return OrderState(
    id=id,
    price=Decimal(str(price)) if price is not None else Decimal(0),
    qty=sign * order.get('amount', Decimal(0)),
    filled_qty=sign * Decimal(str(order.get('filledAmount', 0))),
    # A stop-limit order sits `inactive` until its stop price is reached: not yet in
    # the book, but not finished with either.
    active=order.get('status') in ('open', 'inactive'),
    details=order,
  )


def dump_order(symbol: str, order: Order) -> OrderRequest:
  """Map an SDK order onto Bit2Me's order request.

  `MARKET` becomes a native market order, which executes at the best available price
  and ignores the SDK's `price` protection -- Bit2Me offers no worst-price bound on
  one.
  """
  qty = Decimal(order['qty'])
  side: OrderSide = 'buy' if qty > 0 else 'sell'
  amount = str(abs(qty))
  match order['type']:
    case 'MARKET':
      market: MarketOrderRequest = {
        'side': side,
        'symbol': symbol,
        'amount': amount,
        'orderType': 'market',
      }
      return market
    case 'LIMIT' | 'POST_ONLY':
      limit: LimitOrderRequest = {
        'side': side,
        'symbol': symbol,
        'amount': amount,
        'orderType': 'limit',
        'price': str(Decimal(order['price'])),
      }
      if order['type'] == 'POST_ONLY':
        limit['postOnly'] = True
      return limit
    case _:
      raise ValidationError(f'Unknown order type: {order["type"]}')


async def open_orders(self: 'MarketMixin') -> Sequence[OrderState]:
  """Fetch the market's currently open orders."""
  out: list[OrderState] = []
  offset = 0
  while True:
    current = offset
    page = await self.call_bit2me(
      lambda: self.client.v1.trading.orders.list(
        symbol=self.symbol, status='open', limit=ORDERS_PAGE, offset=current
      )
    )
    out.extend(parse_order(order) for order in page)
    offset += len(page)
    if len(page) < ORDERS_PAGE:
      return out


async def query_order(self: 'MarketMixin', id: str) -> OrderState | None:
  """Fetch one order by id, whatever its status."""
  order = await self.call_bit2me(lambda: self.client.v1.trading.orders.get(id))
  return parse_order(order)


async def place_order(
  self: 'MarketMixin', order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Place an order in the market."""
  request = dump_order(self.symbol, order)
  placed = await self.call_bit2me(lambda: self.client.v1.trading.orders.create(request))
  id = placed.get('id')
  if id is None:
    raise ValidationError('Bit2Me order response is missing its id')
  return OrderResponse(id=id, details=placed)


async def cancel_order(
  self: 'MarketMixin', id: str, *, settings: Settings = {}
) -> Bit2MeOrder:
  """Cancel an order in the market."""
  return await self.call_bit2me(lambda: self.client.v1.trading.orders.cancel(id))
