from typing_extensions import AsyncIterable, TypedDict
from dataclasses import dataclass, field
import asyncio

from dydx.indexer.types import PerpetualMarket
from dydx.indexer import IndexerData, IndexerStreams
from dydx.indexer.streams.subaccounts import UpdateMessage as SubaccountMessage
from dydx.node import PublicNode, PrivateNode, OEGS_GRPC_URL
from dydx.node.private.place_order import Flags

@dataclass(kw_only=True)
class MarketMixin:
  market: str

@dataclass(kw_only=True)
class IndexerDataMixin:
  indexer_data: IndexerData = field(default_factory=IndexerData)

@dataclass(kw_only=True)
class IndexerStreamsMixin:
  indexer_streams: IndexerStreams = field(default_factory=IndexerStreams)

@dataclass(kw_only=True)
class PublicNodeMixin:
  public_node: PublicNode

@dataclass(kw_only=True)
class AccountMixin:
  address: str

@dataclass(kw_only=True)
class SubaccountMixin(AccountMixin):
  subaccount: int = 0

@dataclass(kw_only=True)
class SubaccountStreamMixin(SubaccountMixin, IndexerStreamsMixin):
  _subaccounts_queues: list[asyncio.Queue[SubaccountMessage]] = field(default_factory=list, init=False, repr=False)
  _subaccounts_listener: asyncio.Task | None = field(default=None, init=False, repr=False)

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
class PrivateNodeMixin:
  private_node: PrivateNode

class TradingSettings(TypedDict, total=False):
  limit_flags: Flags
  """Place limit orders as short/long term"""
  reduce_only: bool

@dataclass(kw_only=True)
class TradingMixin(MarketMixin, IndexerDataMixin, SubaccountMixin, PrivateNodeMixin):
  settings: TradingSettings | None = None
  perpetual_market: PerpetualMarket

  @classmethod
  async def connect(
    cls, mnemonic: str, *,
    market: str,
    node_url: str = OEGS_GRPC_URL,
    subaccount: int = 0,
    validate: bool = True,
    settings: TradingSettings | None = None,
    indexer_data: IndexerData | None = None,
  ):
    node = await PrivateNode.connect(mnemonic, url=node_url)
    indexer_data = indexer_data or IndexerData(default_validate=validate)
    perpetual_market = await indexer_data.get_market(market)
    return cls(
      private_node=node,
      indexer_data=indexer_data,
      settings=settings,
      address=node.address,
      subaccount=subaccount,
      market=market,
      perpetual_market=perpetual_market,
    )