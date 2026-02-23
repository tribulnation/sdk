from typing_extensions import AsyncIterable, TypedDict
from dataclasses import dataclass, field
import asyncio

from mexc import MEXC
from mexc.spot.market_data.exchange_info import Info as SpotInfo
from mexc.spot.streams.user.my_trades import Trade as SpotTrade
from mexc.futures.market_data.contract_info import Info as PerpInfo
from mexc.futures.streams.user.my_trades import Deal as PerpTrade
from .util import StreamManager

class Settings(TypedDict, total=False):
  validate: bool
  recvWindow: int

@dataclass(frozen=True)
class Mixin:
  client: MEXC
  settings: Settings = field(default_factory=Settings)
  stream_manager: dict[str, StreamManager] = field(default_factory=dict, init=False, repr=False)

  @property
  def validate(self) -> bool:
    return self.settings.get('validate', True)

  @property
  def recvWindow(self) -> int | None:
    return self.settings.get('recvWindow', None)

  @classmethod
  def new(
    cls, api_key: str | None = None, api_secret: str | None = None, *,
    settings: Settings = {},
  ):
    client = MEXC.new(api_key=api_key, api_secret=api_secret, validate=settings.get('validate', True))
    return cls(client=client, settings=settings)

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(*[stream.close() for stream in self.stream_manager.values()])
    await self.client.__aexit__(exc_type, exc_value, traceback)


@dataclass(kw_only=True, frozen=True)
class PerpMixin(Mixin):

  class Meta(TypedDict):
    info: PerpInfo
  
  meta: Meta

  @classmethod
  def of(
    cls, meta: Meta, *, client: MEXC,
    settings: Settings = {},
  ):
    return cls(meta=meta, client=client, settings=settings)
  
  
  @property
  def info(self) -> PerpInfo:
    return self.meta['info']

  @property
  def instrument(self) -> str:
    return self.info['symbol']

  async def my_trades_stream(self) -> AsyncIterable[PerpTrade]:
    if 'perp_my_trades' not in self.stream_manager:
      stream = self.client.futures.streams.my_trades()
      self.stream_manager['perp_my_trades'] = StreamManager.of(stream)

    manager: StreamManager[PerpTrade] = self.stream_manager['perp_my_trades']
    async for trade in manager.subscribe():
      if trade['symbol'] == self.instrument:
        yield trade


@dataclass(kw_only=True, frozen=True)
class SpotMixin(Mixin):
  
  class Meta(TypedDict):
    info: SpotInfo

  meta: Meta

  @property
  def info(self) -> SpotInfo:
    return self.meta['info']

  @property
  def instrument(self) -> str:
    return self.info['symbol']

  @classmethod
  def of(
    cls, meta: Meta, *, client: MEXC,
    settings: Settings = {},
  ):
    return cls(meta=meta, client=client, settings=settings)

  async def my_trades_stream(self) -> AsyncIterable[SpotTrade]:
    if 'spot_my_trades' not in self.stream_manager:
      stream = self.client.spot.streams.my_trades()
      self.stream_manager['spot_my_trades'] = StreamManager.of(stream)

    manager: StreamManager[SpotTrade] = self.stream_manager['spot_my_trades']
    async for trade in manager.subscribe():
      yield trade