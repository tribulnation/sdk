from typing_extensions import AsyncIterable, TypedDict
from dataclasses import dataclass, field
import asyncio
import os

from dydx.indexer.types import PerpetualMarket
from dydx.indexer import Indexer
from dydx.indexer.streams.subaccounts import UpdateMessage as SubaccountMessage
from dydx.node import PublicNode, PrivateNode, OEGS_GRPC_URL
from dydx.node.private.place_order import Flags

from .util import StreamManager

class Settings(TypedDict, total=False):
  limit_flags: Flags
  """Place limit orders as short/long term"""
  reduce_only: bool

@dataclass(kw_only=True, frozen=True)
class Mixin:
  address: str
  indexer: Indexer = field(default_factory=Indexer)
  public_node: PublicNode
  private_node: PrivateNode
  streams: dict[str, StreamManager]

  async def __aenter__(self):
    await self.indexer.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(*[stream.close() for stream in self.streams.values()])
    await self.indexer.__aexit__(exc_type, exc_value, traceback)

  @classmethod
  async def connect(
    cls, mnemonic: str | None = None, *,
    node_url: str = OEGS_GRPC_URL,
    validate: bool = True,
    indexer: Indexer | None = None,
  ):
    if mnemonic is None:
      mnemonic = os.environ['DYDX_MNEMONIC']
    private_node = await PrivateNode.connect(mnemonic, url=node_url)
    public_node = PublicNode(node_client=private_node.node_client)
    indexer = indexer or Indexer.new(validate=validate)
    return cls(
      private_node=private_node,
      public_node=public_node,
      indexer=indexer,
      address=private_node.address,
      streams={},
    )

@dataclass(kw_only=True, frozen=True)
class MarketMixin(Mixin):
  perpetual_market: PerpetualMarket
  subaccount: int = 0
  settings: Settings = field(default_factory=Settings)

  @property
  def market(self) -> str:
    return self.perpetual_market['ticker']

  async def subscribe_subaccounts(self) -> AsyncIterable[SubaccountMessage]:
    key = f'subaccount-{self.subaccount}'
    if key not in self.streams:
      _, stream = await self.indexer.streams.subaccounts(self.address, subaccount=self.subaccount, validate=False)
      self.streams[key] = StreamManager.of(stream)

    manager: StreamManager[SubaccountMessage] = self.streams[key]
    async for log in manager.subscribe():
      yield log

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
    )