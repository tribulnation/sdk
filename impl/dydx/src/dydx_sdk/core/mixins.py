from typing_extensions import AsyncIterable
from dataclasses import dataclass, field
from decimal import Decimal
import asyncio

from dydx.core.types import PerpetualMarket
from dydx.indexer import IndexerData, INDEXER_HTTP_URL, IndexerStreams, INDEXER_WS_URL
from dydx.indexer.streams.subaccounts import UpdateMessage as SubaccountMessage
from dydx.node import PrivateNode, OEGS_GRPC_URL
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
  _subaccounts_queues: list[asyncio.Queue[SubaccountMessage]] = field(default_factory=list, init=False, repr=False)
  _subaccounts_listener: asyncio.Task | None = field(default=None, init=False, repr=False)

  @classmethod
  def new(cls, address: str, *, subaccount: int = 0, url: str = INDEXER_WS_URL, validate: bool = True):
    return cls(address=address, subaccount=subaccount, indexer_streams=IndexerStreams.new(url=url, validate=validate))

  async def close(self):
    if self._subaccounts_listener is not None:
      self._subaccounts_listener.cancel()
      self._subaccounts_listener = None

  def __del__(self):
    asyncio.create_task(self.close())

  async def subscribe_subaccounts(self) -> AsyncIterable[SubaccountMessage]:
    queue = asyncio.Queue[SubaccountMessage]()
    self._subaccounts_queues.append(queue)
    
    if self._subaccounts_listener is None:
      async def listener():
        _, stream = await self.indexer_streams.subaccounts(self.address, subaccount=self.subaccount, validate=False)
        async for log in stream:
          for q in self._subaccounts_queues:
            q.put_nowait(log)
      self._subaccounts_listener = asyncio.create_task(listener())

    while True:
      # propagate exceptions raised in the listener
      task = asyncio.create_task(queue.get())
      await asyncio.wait([task, self._subaccounts_listener], return_when='FIRST_COMPLETED')
      if self._subaccounts_listener.done() and (exc := self._subaccounts_listener.exception()) is not None:
        raise exc
      yield await task


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
    node_url: str = OEGS_GRPC_URL,
    indexer_url: str = INDEXER_HTTP_URL,
    validate: bool = True,
    limit_flags: Flags = 'LONG_TERM',
  ):
    node = await PrivateNode.connect(mnemonic, url=node_url)
    indexer_data = IndexerData(url=indexer_url, default_validate=validate)
    return cls(node=node, indexer_data=indexer_data, limit_flags=limit_flags)