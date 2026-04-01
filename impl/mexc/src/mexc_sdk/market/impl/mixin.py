from typing_extensions import TypedDict, Literal
from dataclasses import dataclass, field
import asyncio

from trading_sdk.core import SDK, Stream, Subscription

from mexc import MEXC
from mexc.spot.market_data.exchange_info import Info as SpotInfo
from mexc.spot.streams.core.proto import PublicLimitDepthsV3Api, PrivateDealsV3Api

from mexc_sdk.core.exc import wrap_exceptions

class Settings(TypedDict, total=False):
  validate: bool
  recvWindow: int

class Meta(TypedDict):
  info: SpotInfo

@dataclass(kw_only=True)
class Shared:
  client: MEXC
  settings: Settings = field(default_factory=Settings)

  spot_markets: dict[str, SpotInfo] | None = None
  my_trades_subscription: Subscription[PrivateDealsV3Api] | None = None
  depth_subscriptions: dict[tuple[str, Literal[5, 10, 20]], Subscription[PublicLimitDepthsV3Api]] = field(default_factory=dict)

  _markets_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

  @property
  def validate(self) -> bool:
    return self.settings.get("validate", True)

  @property
  def recvWindow(self) -> int | None:
    return self.settings.get("recvWindow", None)

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    settings: Settings = {},
  ):
    client = MEXC.new(api_key=api_key, api_secret=api_secret, validate=settings.get("validate", True))
    return cls(client=client, settings=settings)

  @classmethod
  def public(cls, *, settings: Settings = {}):
    client = MEXC.public(validate=settings.get("validate", True))
    return cls(client=client, settings=settings)

  @wrap_exceptions
  async def __aenter__(self):
    return self

  @wrap_exceptions
  async def __aexit__(self, exc_type, exc_value, traceback):
    # We intentionally don't enter/exit the typed client's WS contexts here.
    # WS connections are opened lazily when the specific stream subscriptions are used.
    return None

  @wrap_exceptions
  async def load_markets(self, *, refetch: bool = False) -> dict[str, SpotInfo]:
    if not refetch and self.spot_markets is not None:
      return self.spot_markets
    async with self._markets_lock:
      if not refetch and self.spot_markets is not None:
        return self.spot_markets
      self.spot_markets = await self.client.spot.exchange_info(validate=self.validate)
      return self.spot_markets

  def depth_subscription(self, symbol: str, /, *, levels: int | None = None):
    if levels is None:
      lvl = 20
    elif levels <= 5:
      lvl = 5
    elif levels <= 10:
      lvl = 10
    else:
      lvl = 20
      
    key = (symbol, lvl)
    if key not in self.depth_subscriptions:
      async def subscribe() -> Stream[PublicLimitDepthsV3Api]:
        stream = await self.client.spot.streams.depth(symbol, level=lvl)
        return Stream(stream.stream, stream.unsubscribe)
      self.depth_subscriptions[key] = Subscription.of(subscribe)
    return self.depth_subscriptions[key]

  def my_trades_sub(self) -> Subscription[PrivateDealsV3Api]:
    if self.my_trades_subscription is None:
      async def subscribe() -> Stream[PrivateDealsV3Api]:
        stream = await self.client.spot.streams.my_trades()
        return Stream(stream.stream, stream.unsubscribe)
      self.my_trades_subscription = Subscription.of(subscribe)
    return self.my_trades_subscription

@dataclass(frozen=True)
class SharedMixin:
  shared: Shared

  @classmethod
  def new(cls, api_key: str | None = None, api_secret: str | None = None, *, settings: Settings = {}):
    return cls(shared=Shared.new(api_key=api_key, api_secret=api_secret, settings=settings))

  @classmethod
  def public(cls, *, settings: Settings = {}):
    return cls(shared=Shared.public(settings=settings))

  @property
  def client(self) -> MEXC:
    return self.shared.client

  @property
  def settings(self) -> Settings:
    return self.shared.settings

  async def __aenter__(self):
    await self.shared.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.shared.__aexit__(exc_type, exc_value, traceback)

@dataclass(kw_only=True, frozen=True)
class ExchangeMixin(SharedMixin):
  ...

@dataclass(kw_only=True, frozen=True)
class MarketMixin(SDK, ExchangeMixin):
  meta: Meta

  @property
  def info(self) -> SpotInfo:
    return self.meta["info"]

  @property
  def instrument(self) -> str:
    return self.info["symbol"]

  async def subscribe_depth(self, *, levels: int | None = None) -> Stream[PublicLimitDepthsV3Api]:
    return await self.shared.depth_subscription(self.instrument, levels=levels).subscribe()

  async def subscribe_my_trades(self) -> Stream[PrivateDealsV3Api]:
    return await self.shared.my_trades_sub().subscribe()

