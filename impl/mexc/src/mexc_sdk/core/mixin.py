from typing_extensions import AsyncIterable
from dataclasses import dataclass, field
import asyncio

from mexc import MEXC
from mexc.spot.market_data.exchange_info import Info
from mexc.spot.streams.user.my_trades import Trade

@dataclass
class SdkMixin:
  client: MEXC
  validate: bool = True
  recvWindow: int | None = None

  @classmethod
  def new(
    cls, api_key: str | None = None, api_secret: str | None = None, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    client = MEXC.new(api_key=api_key, api_secret=api_secret, validate=validate)
    return cls(client=client, validate=validate, recvWindow=recvWindow)

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)


@dataclass(kw_only=True)
class MarketMixin(SdkMixin):
  instrument: str

@dataclass(kw_only=True)
class SpotMixin(SdkMixin):
  info: Info

  @property
  def instrument(self) -> str:
    return self.info['symbol']


@dataclass(kw_only=True)
class StreamsMixin(SdkMixin):
  _my_trades_queues: list[asyncio.Queue[Trade]] = field(default_factory=list, init=False, repr=False)
  _my_trades_listener: asyncio.Task | None = field(default=None, init=False, repr=False)

  async def __aexit__(self, exc_type, exc_value, traceback):
    if self._my_trades_listener is not None:
      self._my_trades_listener.cancel()
      self._my_trades_listener = None
    await super().__aexit__(exc_type, exc_value, traceback)

  async def my_trades_stream(self) -> AsyncIterable[Trade]:
    queue = asyncio.Queue[Trade]()
    self._my_trades_queues.append(queue)
    
    if self._my_trades_listener is None:
      async def listener():
        async for trade in self.client.spot.streams.my_trades():
          for queue in self._my_trades_queues:
            queue.put_nowait(trade)
      self._my_trades_listener = asyncio.create_task(listener())

    while True:
      # propagate exceptions raised in the listener
      task = asyncio.create_task(queue.get())
      await asyncio.wait([task, self._my_trades_listener], return_when='FIRST_COMPLETED')
      if self._my_trades_listener.done() and (exc := self._my_trades_listener.exception()) is not None:
        raise exc
      yield await task