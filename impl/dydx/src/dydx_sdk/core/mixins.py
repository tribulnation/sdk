from dataclasses import dataclass, field
from decimal import Decimal

from dydx.core.types import PerpetualMarket
from dydx.indexer import IndexerData, INDEXER_HTTP_URL, IndexerStreams, INDEXER_WS_URL
from dydx.node import PrivateNode, POLKACHU_GRPC_URL
from dydx.node.private.place_order import Flags

@dataclass(kw_only=True)
class MarketMixin:
  market: str

@dataclass(kw_only=True)
class MarketDataMixin:
  indexer_data: IndexerData = field(default_factory=IndexerData)

  @classmethod
  def new(cls, url: str = INDEXER_HTTP_URL, *, validate: bool = True):
    return cls(indexer_data=IndexerData(url=url, default_validate=validate))

@dataclass(kw_only=True)
class UserDataMixin:
  address: str
  subaccount: int = 0
  indexer_data: IndexerData = field(default_factory=IndexerData)

  @classmethod
  def new(cls, address: str, *, subaccount: int = 0, url: str = INDEXER_HTTP_URL, validate: bool = True):
    return cls(address=address, subaccount=subaccount, indexer_data=IndexerData(url=url, default_validate=validate))


@dataclass(kw_only=True)
class UserStreamsMixin:
  address: str
  subaccount: int = 0
  indexer_streams: IndexerStreams = field(default_factory=IndexerStreams)

  @classmethod
  def new(cls, address: str, *, subaccount: int = 0, url: str = INDEXER_WS_URL, validate: bool = True):
    return cls(address=address, subaccount=subaccount, indexer_streams=IndexerStreams.new(url=url, validate=validate))


@dataclass(kw_only=True)
class TradingMixin:
  node: PrivateNode
  indexer_data: IndexerData = field(default_factory=IndexerData)
  limit_flags: Flags = 'SHORT_TERM'
  """Place limit orders as short/long term"""
  market_cache: dict[str, PerpetualMarket] = field(default_factory=dict, init=False, repr=False)
  market_buffer: Decimal = Decimal(0.1)
  """Buffer to add to the current price when placing an order (since dYdX doesn't only supports limit orders)"""

  async def fetch_market(self, market: str):
    if market not in self.market_cache:
      self.market_cache[market] = await self.indexer_data.get_market(market, limit=1, unsafe=True)
    return self.market_cache[market]

  @classmethod
  async def connect(
    cls, mnemonic: str, *,
    node_url: str = POLKACHU_GRPC_URL,
    indexer_url: str = INDEXER_HTTP_URL,
    validate: bool = True,
    limit_flags: Flags = 'LONG_TERM',
    market_flags: Flags = 'SHORT_TERM',
  ):
    node = await PrivateNode.connect(mnemonic, url=node_url)
    indexer_data = IndexerData(url=indexer_url, default_validate=validate)
    return cls(node=node, indexer_data=indexer_data, limit_flags=limit_flags, market_flags=market_flags)