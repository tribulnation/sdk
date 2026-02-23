from dataclasses import dataclass

from trading_sdk.market.user import Orders as _Orders

from mexc_sdk.core import PerpMixin

@dataclass(frozen=True)
class Orders(PerpMixin, _Orders):
  async def query(self, id: str) -> _Orders.Order:
    raise NotImplementedError('MEXC futures order query is not implemented')

  async def open(self) -> list[_Orders.Order]:
    raise NotImplementedError('MEXC futures open orders are not implemented')
