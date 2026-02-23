from typing_extensions import Sequence
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.core import ApiError, ValidationError, fmt_num
from trading_sdk.market.trade import Place as _Place
from hyperliquid.exchange.order import Order
from hyperliquid_sdk.core import Settings
from hyperliquid_sdk.perps.core import PerpMixin

def export_order(o: _Place.Order, *, asset: int, settings: Settings) -> Order:
  if o['type'] == 'LIMIT':
    tif = settings.get('limit_tif', 'Gtc')
  elif o['type'] == 'POST_ONLY':
    tif = 'Alo'
  else:
    raise ValidationError(f'Unknown order type: {o["type"]}')
  qty = Decimal(o['qty'])
  return {
    'a': asset,
    'b': qty >= 0,
    'p': fmt_num(o['price']),
    's': fmt_num(abs(qty)),
    'r': settings.get('reduce_only', False),
    't': {
      'limit': {
        'tif': tif
      }
    }
  }

@dataclass(frozen=True)
class Place(PerpMixin, _Place):
  async def orders(self, orders: Sequence[_Place.Order]) -> Sequence[_Place.Result]:
    asset = self.asset_id
    result = await self.client.exchange.order(*(
      export_order(o, asset=asset, settings=self.settings)
      for o in orders
    ))
    if result['status'] != 'ok':
      raise ApiError(result)
    else:
      out: list[_Place.Result] = []
      errors: dict[int, str] = {}
      for i, s in enumerate(result['response']['data']['statuses']):
        if (err := s.get('error')) is not None:
          errors[i] = err
        elif (resting := s.get('resting')) is not None:
          out.append(_Place.Result(id=str(resting['oid']), details=s))
        elif (filled := s.get('filled')) is not None:
          out.append(_Place.Result(id=str(filled['oid']), details=s))
        else:
          errors[i] = f'Unknown status: {s}'
      if errors:
        raise ApiError(errors)
      return out


  async def order(self, order: _Place.Order) -> _Place.Result:
    return (await self.orders([order]))[0]
