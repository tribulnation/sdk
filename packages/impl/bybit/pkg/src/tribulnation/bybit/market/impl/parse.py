"""Mapping between Bybit v5 payloads and the SDK's market types."""

from typing_extensions import Literal, Sequence
from decimal import Decimal

from tribulnation.sdk.market import Book, Order, OrderState, Trade
from typed_bybit.private.execution import ExecutionUpdate
from typed_bybit.schemas import OrderbookLevel
from typed_bybit.trade.create_order import (
  CreateLimitOrderRequest,
  CreateMarketOrderRequest,
)
from typed_bybit.trade.open_orders import OpenOrder
from typed_bybit.trade.trade_history import Execution

Category = Literal['spot', 'linear']
"""The two Bybit v5 product categories this package maps onto SDK exchanges."""

RESTING_STATUSES = ('New', 'PartiallyFilled', 'Untriggered')
"""Order statuses that mean the order is still working on the book."""


def parse_book(bids: Sequence[OrderbookLevel], asks: Sequence[OrderbookLevel]) -> Book:
  """Build a `Book` from Bybit's `b`/`a` level arrays."""
  return Book(
    bids=[Book.Entry(price, qty) for price, qty in bids],
    asks=[Book.Entry(price, qty) for price, qty in asks],
  )


def parse_order(order: OpenOrder) -> OrderState:
  """Map one open order onto an `OrderState`, signing quantities by side."""
  sign = 1 if order['side'] == 'Buy' else -1
  return OrderState(
    id=order['orderId'],
    price=order['price'],
    qty=sign * order['qty'],
    filled_qty=sign * order['cumExecQty'],
    active=order['orderStatus'] in RESTING_STATUSES,
    details=order,
  )


def parse_execution(execution: 'Execution | ExecutionUpdate') -> Trade:
  """Map one execution onto a `Trade`, from either the REST endpoint or the stream.

  The two shapes agree on every field read here, sizes and fees included, so one
  mapping serves both.

  `execFee` is required and already a parsed `Decimal`, so it is read with no
  truthiness guard: a zero fee is a real fee, and 40 of the 55 spot fills on the
  account this was derived against carry exactly `0`.

  An order placed without an `orderLinkId` reports `""` (read as `None`) on linear;
  spot generates one.
  """
  qty = execution['execQty']
  return Trade(
    id=execution['execId'],
    order_id=execution['orderId'],
    client_order_id=execution['orderLinkId'] or None,
    price=execution['execPrice'],
    qty=qty if execution['side'] == 'Buy' else -qty,
    time=execution['execTime'],
    maker=execution['isMaker'],
    fee=Trade.Fee(amount=execution['execFee'], asset=execution['feeCurrency']),
    details=execution,
  )


def order_request(
  category: Category, symbol: str, order: Order
) -> CreateMarketOrderRequest | CreateLimitOrderRequest:
  """Build a Bybit order body from the SDK's signed-quantity `Order`.

  `'MARKET'` becomes a native Bybit market order, which carries its own slippage
  protection and ignores a limit price; `'POST_ONLY'` becomes a `PostOnly` limit
  order, and `'LIMIT'` a `GTC` one. A `client_order_id` is sent as `orderLinkId`.
  """
  qty = Decimal(order['qty'])
  side: Literal['Buy', 'Sell'] = 'Buy' if qty > 0 else 'Sell'
  request: CreateMarketOrderRequest | CreateLimitOrderRequest
  if order['type'] == 'MARKET':
    request = CreateMarketOrderRequest(
      category=category,
      symbol=symbol,
      side=side,
      orderType='Market',
      qty=str(abs(qty)),
      timeInForce='IOC',
    )
  else:
    request = CreateLimitOrderRequest(
      category=category,
      symbol=symbol,
      side=side,
      orderType='Limit',
      qty=str(abs(qty)),
      price=str(Decimal(order['price'])),
      timeInForce='PostOnly' if order['type'] == 'POST_ONLY' else 'GTC',
    )
  if (client_order_id := order.get('client_order_id')) is not None:
    request['orderLinkId'] = client_order_id
  return request
