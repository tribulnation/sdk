from typing_extensions import TypedDict, Callable, Awaitable, TypeVar
from dataclasses import dataclass, field
import asyncio

from dydx.indexer.types import PerpetualMarket
from dydx import Dydx
from dydx.indexer.streams.parent_subaccounts import Notification as ParentSubaccountNotification
from dydx.node.orders import Flags, TimeInForce
from dydx.protos.dydxprotocol import feetiers as feetiers_proto

from tribulnation.sdk.core import SDK, Subscription
from tribulnation.dydx.core import wrap_exceptions
from .depth import depth_stream, Book
from .rules import parse_rules, Rules

T = TypeVar('T')

class Settings(TypedDict, total=False):
  order_flags: Flags
  """Order flags for all orders"""
  limit_tif: TimeInForce
  """Time in force for limit orders"""
  market_tif: TimeInForce
  """Time in force for market orders. Defaults to immediate-or-cancel."""
  short_term_gtb: int
  """GTB delta for short-term orders. The GTB will be `current_block() + short_term_gtb`"""
  long_term_gtbt: int
  """GTBT delta for long-term orders. The GTBT will be `current_block().time.seconds + long_term_gtbt`"""
  reduce_only: bool

@dataclass(kw_only=True)
class Shared:
  client: Dydx
  parent_subaccount: int = 0
  perpetual_markets: dict[str, PerpetualMarket] | None = None
  fee_tier: feetiers_proto.PerpetualFeeTier | None = None
  parent_subaccount_subscriptions: dict[int, Subscription[ParentSubaccountNotification]] = field(default_factory=dict)
  depth_subscriptions: dict[str, Subscription[Book]] = field(default_factory=dict)

  @property
  async def address(self) -> str:
    return self.client.node.require_wallet().address

  @wrap_exceptions
  async def load_markets(self, *, refetch: bool = False) -> dict[str, PerpetualMarket]:
    if refetch or self.perpetual_markets is None:
      self.perpetual_markets = (await self.client.indexer.data.get_markets())['markets']
    return self.perpetual_markets

  @wrap_exceptions
  async def load_fee_tier(self, *, refetch: bool = False) -> feetiers_proto.PerpetualFeeTier:
    if refetch or self.fee_tier is None:
      response = await self.client.chain.feetiers.user_fee_tier(await self.address)
      if response.tier is None:
        raise ValueError('dYdX fee tier response did not include a tier')
      self.fee_tier = response.tier
    return self.fee_tier

  async def rules(self, market: str, *, refetch: bool = False) -> Rules:
    markets, fee_tier = await asyncio.gather(
      self.load_markets(refetch=refetch),
      self.load_fee_tier(refetch=refetch),
    )
    return parse_rules(markets[market], fee_tier)

  def parent_account_subscription(self, parent_subaccount: int):
    if parent_subaccount not in self.parent_subaccount_subscriptions:
      @wrap_exceptions
      async def subscribe():
        stream = await self.client.indexer.streams.parent_subaccounts(await self.address, subaccount=parent_subaccount)
        @wrap_exceptions
        async def parsed_stream():
          async for msg in stream:
            yield msg
        return parsed_stream(), stream.unsubscribe
      self.parent_subaccount_subscriptions[parent_subaccount] = Subscription.of(subscribe)
    return self.parent_subaccount_subscriptions[parent_subaccount]

  def depth_subscription(self, market: str):
    if market not in self.depth_subscriptions:
      self.depth_subscriptions[market] = Subscription.of(lambda: depth_stream(self.client.indexer, market))
    return self.depth_subscriptions[market]

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)

@dataclass(kw_only=True, frozen=True)
class ExchangeMixin:
  shared: Shared

  @wrap_exceptions
  async def call_dydx(self, fn: Callable[[], Awaitable[T]]) -> T:
    return await fn()

  @classmethod
  def new(cls, mnemonic: str | None = None, *, mainnet: bool = True, validate: bool = True, parent_subaccount: int = 0):
    client = Dydx.mainnet(mnemonic, indexer={'validate': validate}, public=mnemonic is None) if mainnet else Dydx.testnet(mnemonic, indexer={'validate': validate}, public=mnemonic is None)
    return cls(shared=Shared(client=client, parent_subaccount=parent_subaccount))
    
  @property
  def client(self):
    return self.shared.client

  @property
  def indexer(self):
    return self.shared.client.indexer

  @property
  def address(self):
    return self.shared.address

  async def __aenter__(self):
    await self.shared.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.shared.__aexit__(exc_type, exc_value, traceback)

  def subscribe_parent_subaccount(self, parent_subaccount: int):
    return self.shared.parent_account_subscription(parent_subaccount).subscribe()

  def subscribe_depth(self, market: str):
    return self.shared.depth_subscription(market).subscribe()

@dataclass(kw_only=True, frozen=True)
class MarketMixin(SDK, ExchangeMixin):
  perpetual_market: PerpetualMarket
  subaccount: int = 0

  @property
  def market(self) -> str:
    return self.perpetual_market['ticker']
