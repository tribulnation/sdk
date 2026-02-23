from typing_extensions import Literal, AsyncIterable, TypedDict
from dataclasses import dataclass, field
import asyncio
import os

from hyperliquid import Hyperliquid, Wallet
from hyperliquid.exchange.order import TimeInForce
from hyperliquid.streams.user_fills import WsFill, WsUserFills
from .util import StreamManager

class Settings(TypedDict, total=False):
  validate: bool
  reduce_only: bool
  limit_tif: TimeInForce

@dataclass(kw_only=True, frozen=True)
class Mixin:
  address: str
  client: Hyperliquid
  streams: dict[str, StreamManager]
  settings: Settings = field(default_factory=Settings)

  @property
  def validate(self) -> bool:
    return self.settings.get('validate', True)

  @classmethod
  def new(
    cls, address: str | None = None, *, wallet: Wallet | None = None,
    mainnet: bool = True, settings: Settings = {},
    protocol: Literal['http', 'ws'] = 'http',
  ):
    if address is None:
      address = os.environ['HYPERLIQUID_ADDRESS']
    if protocol == 'http':
      client = Hyperliquid.http(wallet, mainnet=mainnet, validate=settings.get('validate', True))
    else:
      client = Hyperliquid.ws(wallet, mainnet=mainnet, validate=settings.get('validate', True))
    return cls(address=address, client=client, settings=settings, streams={})

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(*[stream.close() for stream in self.streams.values()])
    await self.client.__aexit__(exc_type, exc_value, traceback)

  async def subscribe_user_fills(self) -> AsyncIterable[list[WsFill]]:
    if 'user_fills' not in self.streams:
      stream = await self.client.streams.user_fills(self.address, aggregate_by_time=True)
      self.streams['user_fills'] = StreamManager.of(stream)
    
    manager: StreamManager[WsUserFills] = self.streams['user_fills']
    async for chunk in manager.subscribe():
      if not chunk.get('isSnapshot'):
        yield chunk['fills']
