from typing_extensions import Sequence
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.trade import Place as _Place
from trading_sdk.core import ValidationError

from dydx_v4_client.node.builder import TxOptions
from dydx.node.private.place_order import Order, TimeInForce, Flags
from dydx_sdk.core import MarketMixin, wrap_exceptions, Settings
from dydx_sdk.market.user.orders import serialize_id

def time_in_force(order: _Place.Order, settings: Settings) -> TimeInForce:
  match order['type']:
    case 'POST_ONLY':
      return 'POST_ONLY'
    case _:
      return settings.get('limit_tif', 'GOOD_TIL_TIME')

def export_order(
  order: _Place.Order, settings: Settings
) -> Order:
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  return Order(
    side=side,
    price=Decimal(order['price']),
    size=abs(signed_qty),
    flags=settings.get('order_flags', 'LONG_TERM'),
    time_in_force=time_in_force(order, settings),
    reduce_only=settings.get('reduce_only', False),
  )
    
@dataclass(frozen=True)
class Place(MarketMixin, _Place):
  @wrap_exceptions
  async def order(self, order: _Place.Order) -> _Place.Result:
    dydx_order = export_order(order, self.settings)
    r = await self.private_node.place_order(
      self.perpetual_market, dydx_order, subaccount=self.subaccount,
      gtb_delta=self.settings.get('short_term_gtb'),
      gtbt_delta=self.settings.get('long_term_gtbt')
    )
    id = serialize_id(r['order'].order_id)
    return _Place.Result(id=id, details=r)

  @wrap_exceptions
  async def orders(self, orders: Sequence[_Place.Order]) -> Sequence[_Place.Result]:
    results: list[_Place.Result] = []
    # handle sequences serially to avoid nonce issues
    tx_options: TxOptions | None = None
    for order in orders:
      dydx_order = export_order(order, self.settings)
      r = await self.private_node.place_order(
        self.perpetual_market, dydx_order, subaccount=self.subaccount,
        tx_options=tx_options, gtb_delta=self.settings.get('short_term_gtb'),
        gtbt_delta=self.settings.get('long_term_gtbt')
      )
      if tx_options is None:
        tx_options = TxOptions(
          sequence=self.private_node.wallet.sequence,
          account_number=self.private_node.wallet.account_number,
          authenticators=[],
        )
      tx_options.sequence += 1
      id = serialize_id(r['order'].order_id)
      results.append(_Place.Result(id=id, details=r))
    return results