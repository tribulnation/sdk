from typing_extensions import Literal
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.trading.place_order import (
  PlaceOrder as _PlaceOrder, Order as _Order, OrderState
)

from dydx.node.private.place_order import Order, TimeInForce, Flags
from dydx.indexer.types import PerpetualMarket

def market_price(order: _Order, market: PerpetualMarket, *, buffer: Decimal = Decimal(0.1)) -> Decimal:
  if Decimal(order['qty']) > 0:
      return Decimal(market['oraclePrice'])*(1+buffer)
  else:
      return Decimal(market['oraclePrice'])*(1-buffer)

def order_price(order: _Order, market: PerpetualMarket, *, buffer: Decimal = Decimal(0.1)) -> Decimal:
  match order['type']:
    case 'LIMIT':
      return Decimal(order['price'])
    case 'MARKET':
      return market_price(order, market, buffer=buffer)

def time_in_force(order: _Order) -> TimeInForce:
  match order['type']:
    case 'LIMIT' if order.get('post_only'):
      return 'POST_ONLY'
    case 'LIMIT':
      return 'GOOD_TIL_TIME'
    case 'MARKET':
      return 'IMMEDIATE_OR_CANCEL'

def export_order(
  order: _Order, market: PerpetualMarket,
  *, limit_flags: Flags, market_buffer: Decimal
) -> Order:
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  return Order(
    side=side,
    price=order_price(order, market, buffer=market_buffer),
    size=abs(signed_qty),
    flags=limit_flags if order['type'] == 'LIMIT' else 'SHORT_TERM',
    time_in_force=time_in_force(order),
  )
    