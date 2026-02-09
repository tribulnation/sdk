from typing_extensions import Literal
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.trading.place_order import (
  PlaceOrder as _PlaceOrder, Order as _Order, OrderState
)

from dydx.node.private.place_order import Order, TimeInForce
from dydx.core.types import PerpetualMarket
from dydx_sdk.core import MarketMixin, TradingMixin, wrap_exceptions, perp_name
from .query_order import query_order

def market_price(order: _Order, market: PerpetualMarket, *, buffer: Decimal = Decimal(0.1)) -> Decimal:
  match order['side']:
    case 'BUY':
      return Decimal(market['oraclePrice'])*(1+buffer)
    case 'SELL':
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

@dataclass
class PlaceOrder(MarketMixin, TradingMixin, _PlaceOrder):

  def parse_order(self, order: _Order, market: PerpetualMarket) -> Order:
    return Order(
      side=order['side'],
      price=order_price(order, market, buffer=self.market_buffer),
      size=Decimal(order['qty']),
      flags=self.limit_flags if order['type'] == 'LIMIT' else 'SHORT_TERM',
      time_in_force=time_in_force(order),
    )
      
  @wrap_exceptions
  async def _place_order_impl(
    self, order: _Order, *,
    response: Literal['id', 'state'] = 'id'
  ) -> str | OrderState:
    market = await self.fetch_market(self.market)
    r = await self.node.place_order(market, self.parse_order(order, market), unsafe=True)
    id = r['order'].order_id.SerializeToString().decode()
    if response == 'id':
      return id
    else:
      return await query_order(self.indexer_data, address=self.node.address, instrument=self.market, id=id)
