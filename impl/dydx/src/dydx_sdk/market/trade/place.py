from typing_extensions import Sequence
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.trade import Place as _Place
from trading_sdk.core import ValidationError

from dydx_v4_client.node.builder import TxOptions
from dydx.node.private.place_order import Order, TimeInForce, Flags
from dydx_sdk.core import MarketMixin, wrap_exceptions
from dydx_sdk.market.user.orders import serialize_id

def time_in_force(order: _Place.Order, limit_flags: Flags) -> TimeInForce:
  match order['type']:
    case 'POST_ONLY':
      return 'POST_ONLY'
    case 'LIMIT' if limit_flags == 'LONG_TERM':
      return 'GOOD_TIL_TIME'
    case 'LIMIT' if limit_flags == 'SHORT_TERM':
      return 'IMMEDIATE_OR_CANCEL'
    case 'MARKET':
      return 'IMMEDIATE_OR_CANCEL'
    case other:
      raise ValidationError(f'Unknown order type "{other}" with limit flags "{limit_flags}"')

def export_order(
  order: _Place.Order, *, limit_flags: Flags | None = None, reduce_only: bool | None = None
) -> Order:
  limit_flags = limit_flags or 'LONG_TERM'
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  return Order(
    side=side,
    price=Decimal(order['price']),
    size=abs(signed_qty),
    flags=limit_flags,
    time_in_force=time_in_force(order, limit_flags),
    reduce_only=reduce_only or False,
  )
    
@dataclass(frozen=True)
class Place(MarketMixin, _Place):
  @wrap_exceptions
  async def order(self, order: _Place.Order) -> _Place.Result:
    dydx_order = export_order(order, limit_flags=self.settings.get('limit_flags'), reduce_only=self.settings.get('reduce_only'))
    r = await self.private_node.place_order(self.perpetual_market, dydx_order, subaccount=self.subaccount)
    id = serialize_id(r['order'].order_id)
    return _Place.Result(id=id, details=r)

  @wrap_exceptions
  async def orders(self, orders: Sequence[_Place.Order]) -> Sequence[_Place.Result]:
    results: list[_Place.Result] = []
    # handle sequences serially to avoid nonce issues
    tx_options: TxOptions | None = None
    for order in orders:
      dydx_order = export_order(order, limit_flags=self.settings.get('limit_flags'), reduce_only=self.settings.get('reduce_only'))
      r = await self.private_node.place_order(
        self.perpetual_market, dydx_order, subaccount=self.subaccount,
        tx_options=tx_options
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