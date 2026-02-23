from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpUserData
from hyperliquid_sdk.perps.core import PerpMixin
from .balances import Balances
from .funding import Funding
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(PerpMixin, PerpUserData):
  Balances = Balances
  Funding = Funding
  Orders = Orders
  Position = Position
  Trades = Trades
  balances: Balances
  funding: Funding
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def of(cls, other: 'PerpMixin'):
    return cls(
      address=other.address,
      client=other.client,
      settings=other.settings,
      streams=other.streams,
      meta=other.meta,
      balances=Balances.of(other),
      funding=Funding.of(other),
      orders=Orders.of(other),
      position=Position.of(other),
      trades=Trades.of(other),
    )