from typing_extensions import AsyncIterable, TypedDict
from dataclasses import dataclass, field
import asyncio

from dydx.indexer.types import PerpetualMarket
from dydx.indexer import Indexer
from dydx.indexer.streams.subaccounts import UpdateMessage as SubaccountMessage
from dydx.node import PublicNode, PrivateNode, OEGS_GRPC_URL
from dydx.node.private.place_order import Flags

class TradingSettings(TypedDict, total=False):
  limit_flags: Flags
  """Place limit orders as short/long term"""
  reduce_only: bool

@dataclass(kw_only=True)
class BaseMixin:
  perpetual_market: PerpetualMarket
  address: str
  subaccount: int = 0
  indexer: Indexer = field(default_factory=Indexer)
  public_node: PublicNode
  private_node: PrivateNode
  settings: TradingSettings = field(default_factory=TradingSettings)

  @property
  def market(self) -> str:
    return self.perpetual_market['ticker']

  @classmethod
  async def connect(
    cls, mnemonic: str, *,
    market: str,
    node_url: str = OEGS_GRPC_URL,
    subaccount: int = 0,
    validate: bool = True,
    settings: TradingSettings = {},
    indexer: Indexer | None = None,
  ):
    private_node = await PrivateNode.connect(mnemonic, url=node_url)
    public_node = PublicNode(node_client=private_node.node_client)
    indexer = indexer or Indexer.new(validate=validate)
    perpetual_market = await indexer.data.get_market(market)
    return cls(
      private_node=private_node,
      public_node=public_node,
      indexer=indexer,
      settings=settings,
      address=private_node.address,
      subaccount=subaccount,
      perpetual_market=perpetual_market,
    )

  async def __aenter__(self):
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    ...


@dataclass(kw_only=True)
class Mixin(BaseMixin):
  _subaccounts_queues: list[asyncio.Queue[SubaccountMessage]] = field(default_factory=list)
  _subaccounts_listener: asyncio.Task | None = field(default=None)

  @classmethod
  def of(cls, other: 'Mixin'):
    return cls(
      perpetual_market=other.perpetual_market,
      address=other.address,
      subaccount=other.subaccount,
      indexer=other.indexer,
      public_node=other.public_node,
      private_node=other.private_node,
      settings=other.settings,
      _subaccounts_queues=other._subaccounts_queues,
      _subaccounts_listener=other._subaccounts_listener,
    )

  async def close(self):
    if self._subaccounts_listener is not None:
      self._subaccounts_listener.cancel()
      self._subaccounts_listener = None

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.close()

  async def subscribe_subaccounts(self) -> AsyncIterable[SubaccountMessage]:
    queue = asyncio.Queue[SubaccountMessage]()
    self._subaccounts_queues.append(queue)
    
    if self._subaccounts_listener is None:
      async def listener():
        _, stream = await self.indexer.streams.subaccounts(self.address, subaccount=self.subaccount, validate=False)
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