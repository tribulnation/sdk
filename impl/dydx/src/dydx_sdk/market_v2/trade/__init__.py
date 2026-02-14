from dataclasses import dataclass as _dataclass

from dydx.indexer import IndexerData as _IndexerData
from dydx.node import PrivateNode as _PrivateNode
from dydx.indexer.types import PerpetualMarket as _PerpetualMarket
from dydx.node.private.place_order import Flags as _Flags

from tribulnation.sdk.market_v2 import Trading as _Trading
from .cancel import Cancel
from .place import Place

@_dataclass(frozen=True)
class Trading(_Trading):
  cancel: Cancel
  place: Place

  @classmethod
  def new(
    cls, market: str, *,
    address: str,
    subaccount: int = 0,
    indexer_data: _IndexerData,
    private_node: _PrivateNode,
    limit_flags: _Flags,
    perpetual_market: _PerpetualMarket,
  ):
    return cls(
      cancel=Cancel(private_node=private_node),
      place=Place(
        private_node=private_node, indexer_data=indexer_data,
        address=address, subaccount=subaccount,
        market=market, limit_flags=limit_flags,
        perpetual_market=perpetual_market,
      ),
    )
