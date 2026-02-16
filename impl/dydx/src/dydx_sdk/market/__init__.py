from dataclasses import dataclass as _dataclass

from dydx.indexer import Indexer as _Indexer
from dydx.indexer.types import PerpetualMarket as _PerpetualMarket
from dydx.node import (
  PrivateNode as _PrivateNode,
  PublicNode as _PublicNode,
)
from dydx_sdk.core import TradingSettings as _TradingSettings

from trading_sdk.market import PerpMarket
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True)
class Market(PerpMarket):
  data: MarketData
  user: UserData
  trade: Trading

  @classmethod
  def new(
    cls, market: str, *, address: str, subaccount: int = 0,
    perpetual_market: _PerpetualMarket, settings: _TradingSettings | None = None,
    indexer: _Indexer | None = None, node: _PrivateNode,
  ):
    indexer = indexer or _Indexer()
    public_node = _PublicNode(node_client=node.node_client)
    return cls(
      data=MarketData.new(market, address=address, indexer_data=indexer.data, public_node=public_node),
      user=UserData.new(market, address=address, subaccount=subaccount, indexer=indexer),
      trade=Trading.new(
        market, address=address, subaccount=subaccount, indexer_data=indexer.data,
        private_node=node, settings=settings, perpetual_market=perpetual_market,
      )
    )
