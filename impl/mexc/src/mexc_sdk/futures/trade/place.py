from dataclasses import dataclass

from trading_sdk.market.trade import Place as _Place

from mexc_sdk.core import MarketMixin

@dataclass
class Place(MarketMixin, _Place):
  async def order(self, order: _Place.Order) -> _Place.Result:
    raise NotImplementedError('MEXC futures order placement is not implemented')
