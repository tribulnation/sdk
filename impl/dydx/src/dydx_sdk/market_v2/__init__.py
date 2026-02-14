from dataclasses import dataclass as _dataclass

from dydx.indexer import IndexerData as _IndexerData, INDEXER_HTTP_URL as _INDEXER_HTTP_URL
from dydx.node import (
  PrivateNode as _PrivateNode,
  PublicNode as _PublicNode,
  OEGS_GRPC_URL as _OEGS_GRPC_URL,
)
from dydx.indexer.types import PerpetualMarket as _PerpetualMarket
from dydx.node.private.place_order import Flags as _Flags

from tribulnation.sdk.market_v2 import PerpMarket
from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True)
class Market(PerpMarket):
  data: MarketData
  user: UserData
  trade: Trading

  @classmethod
  async def connect(
    cls, market: str, *,
    mnemonic: str | None = None,
    subaccount: int = 0,
    validate: bool = True,
    node_url: str = _OEGS_GRPC_URL,
    indexer_url: str = _INDEXER_HTTP_URL,
    limit_flags: _Flags = 'LONG_TERM',
  ):
    if mnemonic is None:
      import os
      mnemonic = os.environ['DYDX_MNEMONIC']
    indexer_data = _IndexerData(url=indexer_url, default_validate=validate)
    node = await _PrivateNode.connect(mnemonic, url=node_url, rest_indexer=indexer_url)
    address = node.address
    public_node = _PublicNode(node_client=node.node_client)
    perpetual_market = await indexer_data.get_market(market)
    return cls(
      data=MarketData.new(market, address=address, indexer_data=indexer_data, public_node=public_node),
      user=UserData.new(market, address=address, subaccount=subaccount, indexer_data=indexer_data),
      trade=Trading.new(
        market, address=address, subaccount=subaccount, indexer_data=indexer_data,
        private_node=node, limit_flags=limit_flags, perpetual_market=perpetual_market,
      ),
    )