from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpUserData
from dydx_sdk.core import Mixin as _Mixin
from .balances import Balances
from .funding import Funding
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(PerpUserData):
  balances: Balances
  funding: Funding
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def of(cls, base: _Mixin):
    return cls(
      balances=Balances.of(base),
      funding=Funding.of(base),
      orders=Orders.of(base),
      position=Position.of(base),
      trades=Trades.of(base),
    )
