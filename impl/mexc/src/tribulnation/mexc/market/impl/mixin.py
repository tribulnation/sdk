from typing_extensions import Literal, TypedDict
from dataclasses import dataclass, field
import asyncio

from tribulnation.sdk.core import SDK, Stream, Subscription

from mexc import MEXC
from mexc.spot.market.exchange_info import SymbolInfo
from mexc.spot.streams.core.proto import PublicAggreDepthsV3Api, PrivateDealsV3Api

from tribulnation.mexc.core.exc import wrap_exceptions

SpotInfo = SymbolInfo

class Meta(TypedDict):
  info: SpotInfo

@dataclass(kw_only=True)
class Shared:
  client: MEXC
  validate: bool = True
  recv_window: int | None = None

  spot_markets: dict[str, SpotInfo] | None = None
  my_trades_subscription: Subscription[PrivateDealsV3Api] | None = None
  depth_subscriptions: dict[str, Subscription[PublicAggreDepthsV3Api]] = field(default_factory=dict)

  _markets_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    validate: bool = True,
    recv_window: int | None = None,
  ):
    import os
    api_key = api_key or os.environ.get('MEXC_API_KEY') or ''
    api_secret = api_secret or os.environ.get('MEXC_API_SECRET') or ''
    client = MEXC.new(api_key=api_key, api_secret=api_secret, validate=validate)
    return cls(client=client, validate=validate, recv_window=recv_window)

  @classmethod
  def public(cls, *, validate: bool = True):
    client = MEXC.public(validate=validate)
    return cls(client=client, validate=validate)

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
      info = await self.client.spot.market.exchange_info(validate=self.validate)
      markets = {
        market['symbol']: market
        for market in info['symbols']
        if 'symbol' in market
      }
      self.spot_markets = markets
      return self.spot_markets

  def depth_subscription(self, symbol: str):
    if symbol not in self.depth_subscriptions:
      @wrap_exceptions
      async def subscribe() -> Stream[PublicAggreDepthsV3Api]:
        stream = await self.client.spot.streams.market.depth_updates(symbol, aggregation='10ms')
        return Stream(stream.stream, stream.unsubscribe)
      self.depth_subscriptions[symbol] = Subscription.of(subscribe)
    return self.depth_subscriptions[symbol]

  def my_trades_sub(self) -> Subscription[PrivateDealsV3Api]:
    if self.my_trades_subscription is None:
      @wrap_exceptions
      async def subscribe() -> Stream[PrivateDealsV3Api]:
        stream = await self.client.spot.streams.user.trades()
        return Stream(stream.stream, stream.unsubscribe)
      self.my_trades_subscription = Subscription.of(subscribe)
    return self.my_trades_subscription

@dataclass(frozen=True)
class SharedMixin:
  shared: Shared

  @classmethod
  def new(cls, api_key: str | None = None, api_secret: str | None = None, *, validate: bool = True, recv_window: int | None = None):
    return cls(shared=Shared.new(api_key=api_key, api_secret=api_secret, validate=validate, recv_window=recv_window))

  @classmethod
  def public(cls, *, validate: bool = True):
    return cls(shared=Shared.public(validate=validate))

  @property
  def client(self) -> MEXC:
    return self.shared.client

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
    return self.meta['info']

  @property
  def instrument(self) -> str:
    symbol = self.info.get('symbol')
    if symbol is None:
      raise ValueError('MEXC spot market metadata is missing symbol')
    return symbol

  async def subscribe_depth(self) -> Stream[PublicAggreDepthsV3Api]:
    return await self.shared.depth_subscription(self.instrument).subscribe()

  async def subscribe_my_trades(self) -> Stream[PrivateDealsV3Api]:
    return await self.shared.my_trades_sub().subscribe()
