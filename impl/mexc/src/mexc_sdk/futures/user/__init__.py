from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk.market import PerpUserData as _PerpUserData
from mexc_sdk.core import PerpMixin, Settings
from .balances import Balances
from .position import Position
from .trades import Trades
from .orders import Orders
from .funding import Funding

@_dataclass(frozen=True)
class UserData(PerpMixin, _PerpUserData):
  balances: Balances
  position: Position
  trades: Trades
  orders: Orders
  funding: Funding

  @classmethod
  def of(cls, meta: PerpMixin.Meta, *, client: MEXC, settings: Settings = {}):
    return cls(
      meta=meta, client=client, settings=settings,
      balances=Balances.of(meta=meta, client=client, settings=settings),
      position=Position.of(meta=meta, client=client, settings=settings),
      trades=Trades.of(meta=meta, client=client, settings=settings),
      orders=Orders.of(meta=meta, client=client, settings=settings),
      funding=Funding.of(meta=meta, client=client, settings=settings),
    )
