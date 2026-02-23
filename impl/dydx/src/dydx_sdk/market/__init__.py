from dataclasses import dataclass as _dataclass

from dydx.indexer import Indexer as _Indexer
from dydx.indexer.types import PerpetualMarket as _PerpetualMarket
from dydx.node import (
  PrivateNode as _PrivateNode,
  PublicNode as _PublicNode,
)
from dydx_sdk.core import MarketMixin

from trading_sdk.market import PerpMarket
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True)
class Market(MarketMixin, PerpMarket):
  data: MarketData
  user: UserData
  trade: Trading

  @classmethod
  def of(cls, other: 'MarketMixin'):
    return cls(
      address=other.address,
      indexer=other.indexer,
      public_node=other.public_node,
      private_node=other.private_node,
      streams=other.streams,
      settings=other.settings,
      perpetual_market=other.perpetual_market,
      subaccount=other.subaccount,
      data=MarketData.of(other),
      user=UserData.of(other),
      trade=Trading.of(other),
    )

  @property
  def venue(self) -> str:
    return 'dydx'

  @property
  def market_id(self) -> str:
    return self.market

  @property
  def market(self) -> str:
    return self.perpetual_market['ticker']
