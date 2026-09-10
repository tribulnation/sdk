from typing_extensions import (
  AsyncContextManager,
  Iterable,
  TypedDict,
  Callable,
  Awaitable,
  TypeVar,
)
from dataclasses import dataclass, field
import asyncio
import pydantic

from typed_dydx.indexer.schemas import PerpetualMarket
from typed_dydx import Dydx
from typed_dydx.indexer.schemas import (
  SubaccountsNotification as ParentSubaccountNotification,
)
from typed_dydx.node.orders.types import Flags, TimeInForce
from typed_dydx.protos.dydxprotocol import feetiers as feetiers_proto
from tribulnation.sdk.core import SDK, Subscription, OverflowPolicy, AuthError
from tribulnation.dydx.core import wrap_exceptions
from .depth import depth_stream, Book
from .rules import parse_rules, Rules
from .fees import combined_fees, market_charge, market_discount_params, PPM
from tribulnation.sdk.market import Fees

T = TypeVar('T')


@pydantic.with_config({'extra': 'forbid'})
class Settings(TypedDict, total=False):
  tickers_fetch_depth: bool
  """Whether bulk tickers fetch order books for best bid and ask. Defaults to True."""
  tickers_depth_concurrent: int
  """Maximum concurrent order-book requests used to enrich bulk tickers. Defaults to 20."""
  flags: Flags
  """Order flags. Defaults to SHORT_TERM for market orders and LONG_TERM for limit/post_only orders."""
  tif: TimeInForce
  """Time in force for limit orders. Defaults to IOC for market orders and GTC for limit/post_only orders."""
  short_term_gtb: int
  """GTB delta for short-term orders. The GTB will be `current_block() + short_term_gtb`"""
  long_term_gtbt: int
  """GTBT delta for long-term orders. The GTBT will be `current_block().time.seconds + long_term_gtbt`"""
  reduce_only: bool


settings_adapter = pydantic.TypeAdapter(Settings)


@dataclass(kw_only=True)
class Shared(SDK):
  client: Dydx
  parent_subaccount: int = 0
  address: str | None
  perpetual_markets: dict[str, PerpetualMarket] | None = None
  fee_tier: feetiers_proto.PerpetualFeeTier | None = None
  standard_fee_tier: feetiers_proto.PerpetualFeeTier | None = None
  market_discounts: dict[int, feetiers_proto.PerMarketFeeDiscountParams] | None = None
  parent_subaccount_subscriptions: dict[
    int, Subscription[ParentSubaccountNotification]
  ] = field(default_factory=dict[int, Subscription[ParentSubaccountNotification]])
  depth_subscriptions: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )

  def require_address(self) -> str:
    """Require an account only when an account-scoped operation uses it."""
    if self.address is None:
      raise AuthError('An address or mnemonic is required for account-scoped dYdX data')
    return self.address

  @wrap_exceptions
  async def load_markets(self, *, refetch: bool = False) -> dict[str, PerpetualMarket]:
    if refetch or self.perpetual_markets is None:
      self.perpetual_markets = (await self.client.indexer.data.get_markets())['markets']
    return self.perpetual_markets

  @wrap_exceptions
  async def load_fee_tier(
    self, *, refetch: bool = False
  ) -> feetiers_proto.PerpetualFeeTier:
    if refetch or self.fee_tier is None:
      response = await self.client.chain.feetiers.user_fee_tier(self.require_address())
      if response.tier is None:
        raise ValueError('dYdX fee tier response did not include a tier')
      self.fee_tier = response.tier
    return self.fee_tier

  async def rules(self, market: str, *, refetch: bool = False) -> Rules:
    """Read public metadata and the baseline schedule with active market holidays."""
    markets = await self.load_markets(refetch=refetch)
    fees = await self.fees(markets[market], personal=False, refetch=refetch)
    return parse_rules(markets[market], fees)

  @wrap_exceptions
  async def load_market_charge(
    self, clob_pair_id: int, *, refetch: bool = False
  ) -> int:
    """Load public holiday parameters and evaluate against the latest chain time."""
    if self.market_discounts is None or refetch:
      entries = await market_discount_params(self.client.chain.feetiers)
      discounts = {entry.clob_pair_id: entry for entry in entries}
      if len(discounts) != len(entries):
        raise ValueError('dYdX market fee discounts contain duplicate CLOB pair IDs')
      self.market_discounts = discounts
    discount = self.market_discounts.get(clob_pair_id)
    if discount is None:
      return PPM
    latest = await self.client.chain.tendermint.get_latest_block()
    block = latest.block
    if block is None or block.header is None or block.header.time is None:
      raise ValueError('Latest dYdX block response did not include a timestamp')
    return market_charge(discount, block.header.time)

  @wrap_exceptions
  async def fees(
    self,
    market: PerpetualMarket,
    *,
    personal: bool,
    refetch: bool = False,
  ) -> Fees:
    """Combine the public or referral-adjusted personal tier with all fee discounts."""
    tier, charge = await asyncio.gather(
      self.load_fee_tier(refetch=refetch)
      if personal
      else self.load_standard_fee_tier(refetch=refetch),
      self.load_market_charge(int(market['clobPairId']), refetch=refetch),
    )
    staking_discount = 0
    if personal:
      staking = await self.client.chain.feetiers.user_staking_tier(
        self.require_address()
      )
      if staking.fee_tier_name != tier.name:
        raise ValueError(
          'dYdX account fee tier changed during fee calculation; refetch'
        )
      staking_discount = staking.discount_ppm
    return combined_fees(tier, charge_ppm=charge, staking_discount_ppm=staking_discount)

  @wrap_exceptions
  async def load_standard_fee_tier(
    self, *, refetch: bool = False
  ) -> feetiers_proto.PerpetualFeeTier:
    """Select the public tier without volume/share qualifications."""
    if self.standard_fee_tier is None or refetch:
      response = await self.client.chain.feetiers.perpetual_fee_params()
      if response.params is None:
        raise ValueError('dYdX public fee parameters are missing')
      tiers = [
        tier
        for tier in response.params.tiers
        if tier.absolute_volume_requirement == 0
        and tier.total_volume_share_requirement_ppm == 0
        and tier.maker_volume_share_requirement_ppm == 0
      ]
      if len(tiers) != 1:
        raise ValueError('dYdX public fee parameters must identify one base tier')
      self.standard_fee_tier = tiers[0]
    return self.standard_fee_tier

  def parent_account_subscription(self, parent_subaccount: int):
    if parent_subaccount not in self.parent_subaccount_subscriptions:

      @wrap_exceptions
      async def subscribe():
        stream = await self.client.indexer.streams.parent_subaccounts(
          self.require_address(), subaccount=parent_subaccount
        )

        @wrap_exceptions
        async def parsed_stream():
          async for msg in stream:
            yield msg

        return parsed_stream(), stream.unsubscribe

      self.parent_subaccount_subscriptions[parent_subaccount] = Subscription.of(
        subscribe
      )
    return self.parent_subaccount_subscriptions[parent_subaccount]

  def depth_subscription(self, market: str):
    if market not in self.depth_subscriptions:
      self.depth_subscriptions[market] = Subscription.of(
        lambda: depth_stream(self.client.indexer, market)
      )
    return self.depth_subscriptions[market]

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.client


@dataclass(kw_only=True, frozen=True)
class ExchangeMixin(SDK):
  shared: Shared

  @SDK.method
  @wrap_exceptions
  async def call_dydx(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Retry individual translated requests through the caller's SDK context."""
    return await fn()

  @classmethod
  def new(
    cls,
    mnemonic: str | None = None,
    *,
    address: str | None = None,
    mainnet: bool = True,
    validate: bool = True,
    parent_subaccount: int = 0,
  ):
    client = (
      Dydx.mainnet(mnemonic, indexer={'validate': validate}, public=mnemonic is None)
      if mainnet
      else Dydx.testnet(
        mnemonic, indexer={'validate': validate}, public=mnemonic is None
      )
    )
    if address is None and mnemonic is not None:
      address = client.node.require_wallet().address
    return cls(
      shared=Shared(client=client, address=address, parent_subaccount=parent_subaccount)
    )

  @property
  def client(self):
    return self.shared.client

  @property
  def indexer(self):
    return self.shared.client.indexer

  @property
  def address(self):
    return self.shared.require_address()

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.shared

  def subscribe_parent_subaccount(
    self,
    parent_subaccount: int,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ):
    return self.shared.parent_account_subscription(parent_subaccount).subscribe(
      queue_size=queue_size, overflow=overflow
    )

  def subscribe_depth(
    self, market: str, *, queue_size: int = 1, overflow: OverflowPolicy = 'latest'
  ):
    return self.shared.depth_subscription(market).subscribe(
      queue_size=queue_size, overflow=overflow
    )


@dataclass(kw_only=True, frozen=True)
class MarketMixin(ExchangeMixin):
  perpetual_market: PerpetualMarket
  subaccount: int = 0

  @property
  def market(self) -> str:
    return self.perpetual_market['ticker']
