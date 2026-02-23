from dataclasses import dataclass

from trading_sdk.market.trade import Place as _Place

from mexc_sdk.core import PerpMixin

@dataclass(frozen=True)
class Place(PerpMixin, _Place):
  async def order(self, order: _Place.Order) -> _Place.Result:
    raise NotImplementedError('MEXC futures do not allow API trading')
