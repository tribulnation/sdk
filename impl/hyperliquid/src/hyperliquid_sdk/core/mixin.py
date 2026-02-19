from typing_extensions import Literal, AsyncIterable, TypedDict
from dataclasses import dataclass, field
import asyncio
import os

from hyperliquid import Hyperliquid, Wallet
from hyperliquid.exchange.order import TimeInForce
from hyperliquid.streams.user_fills import WsFill

class TradingSettings(TypedDict, total=False):
  reduce_only: bool
  limit_tif: TimeInForce

@dataclass(kw_only=True, frozen=True)
class BaseMixin:
  address: str
  client: Hyperliquid
  validate: bool = True

  @classmethod
  def new(
    cls, address: str | None = None, *, wallet: Wallet | None = None,
    mainnet: bool = True, validate: bool = True,
    protocol: Literal['http', 'ws'] = 'http',
  ):
    if address is None:
      address = os.environ['HYPERLIQUID_ADDRESS']
    if protocol == 'http':
      client = Hyperliquid.http(wallet, mainnet=mainnet, validate=validate)
    else:
      client = Hyperliquid.ws(wallet, mainnet=mainnet, validate=validate)
    return cls(address=address, client=client, validate=validate)
  
  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)


@dataclass(kw_only=True, frozen=True)
class Mixin(BaseMixin):
  _user_fills_queues: list[asyncio.Queue[list[WsFill]]] = field(default_factory=list, init=False, repr=False)
  _user_fills_listener: asyncio.Task | None = field(default=None, init=False, repr=False)

  async def __aexit__(self, exc_type, exc_value, traceback):
    if self._user_fills_listener is not None:
      self._user_fills_listener.cancel()
      self._user_fills_listener = None
    await super().__aexit__(exc_type, exc_value, traceback)

  async def subscribe_user_fills(self) -> AsyncIterable[list[WsFill]]:
    queue = asyncio.Queue[list[WsFill]]()
    self._user_fills_queues.append(queue)
    
    if self._user_fills_listener is None:
      async def listener():
        stream = await self.client.streams.user_fills(self.address, aggregate_by_time=True)
        async for chunk in stream:
          if not chunk.get('isSnapshot'):
            for q in self._user_fills_queues:
              q.put_nowait(chunk['fills'])
      self._user_fills_listener = asyncio.create_task(listener())

    while True:
      # propagate exceptions raised in the listener
      task = asyncio.create_task(queue.get())
      await asyncio.wait([task, self._user_fills_listener], return_when='FIRST_COMPLETED')
      if self._user_fills_listener.done() and (exc := self._user_fills_listener.exception()) is not None:
        raise exc
      yield await task
