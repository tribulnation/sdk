from dataclasses import dataclass as _dataclass

from trading_sdk.market import UserData as _UserData
from hyperliquid_sdk.spot.core import SpotMixin
from .balances import Balances
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(SpotMixin, _UserData):
  Balances = Balances
  Orders = Orders
  Position = Position
  Trades = Trades
  balances: Balances
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def of(cls, other: 'SpotMixin'):
    return cls(
      address=other.address,
      client=other.client,
      settings=other.settings,
      streams=other.streams,
      meta=other.meta,
      balances=Balances.of(other),
      orders=Orders.of(other),
      position=Position.of(other),
      trades=Trades.of(other),
    )