from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk.market import UserData as _UserData
from mexc_sdk.core import SpotMixin, Settings
from .balances import Balances
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(SpotMixin, _UserData):
  balances: Balances
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def of(cls, meta: SpotMixin.Meta, *, client: MEXC, settings: Settings = {}):
    return cls(
      meta=meta, client=client, settings=settings,
      balances=Balances.of(meta=meta, client=client, settings=settings),
      orders=Orders.of(meta=meta, client=client, settings=settings),
      position=Position.of(meta=meta, client=client, settings=settings),
      trades=Trades.of(meta=meta, client=client, settings=settings),
    )