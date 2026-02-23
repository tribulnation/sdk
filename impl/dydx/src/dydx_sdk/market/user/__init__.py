from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpUserData
from dydx_sdk.core import MarketMixin
from .balances import Balances
from .funding import Funding
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(MarketMixin, PerpUserData):
  balances: Balances
  funding: Funding
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def of(cls, other: MarketMixin):
    return cls(
      address=other.address,
      indexer=other.indexer,
      public_node=other.public_node,
      private_node=other.private_node,
      streams=other.streams,
      settings=other.settings,
      perpetual_market=other.perpetual_market,
      subaccount=other.subaccount,
      balances=Balances.of(other),
      funding=Funding.of(other),
      orders=Orders.of(other),
      position=Position.of(other),
      trades=Trades.of(other),
    )
