from dataclasses import dataclass as _dataclass

from dydx.indexer import Indexer as _Indexer
from dydx.indexer.types import PerpetualMarket as _PerpetualMarket
from dydx.node import (
  PrivateNode as _PrivateNode,
  PublicNode as _PublicNode,
)
from dydx_sdk.core import TradingSettings as _TradingSettings, Mixin as _Mixin

from trading_sdk.market import PerpMarket
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True)
class Market(PerpMarket):
  data: MarketData
  user: UserData
  trade: Trading
  market: str

  @classmethod
  def new(
    cls, market: str, *, address: str, subaccount: int = 0,
    perpetual_market: _PerpetualMarket, settings: _TradingSettings | None = None,
    indexer: _Indexer | None = None, node: _PrivateNode,
  ):
    indexer = indexer or _Indexer()
    public_node = _PublicNode(node_client=node.node_client)
    base = _Mixin(
      address=address, subaccount=subaccount,
      perpetual_market=perpetual_market, settings=settings,
      indexer=indexer, public_node=public_node, private_node=node,
    )
    return cls(
      market=market,
      data=MarketData.of(base),
      user=UserData.of(base),
      trade=Trading.of(base),
    )

  @property
  def venue(self) -> str:
    return 'dydx'

  @property
  def market_id(self) -> str:
    return self.market
