from functools import cached_property
from typing_extensions import (
  TYPE_CHECKING,
  AsyncContextManager,
  Literal,
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
from typed_dydx.chain import Chain
from typed_dydx.chain.comet.core import CometClient
from typed_core.grpc import GrpcClient
from typed_dydx.indexer.schemas import (
  SubaccountsNotification as ParentSubaccountNotification,
)
from typed_dydx.node.orders.types import Flags, TimeInForce
from typed_dydx.protos.dydxprotocol import feetiers as feetiers_proto
from tribulnation.sdk.core import (
  ManagedResource,
  SDK,
  Subscription,
  OverflowPolicy,
  AuthError,
)
from tribulnation.dydx.core import wrap_exceptions
from .depth import depth_stream, Book
from .rules import parse_rules, Rules
from .fees import combined_fees, market_charge, market_discount_params, PPM
from tribulnation.sdk.market import Fees

if TYPE_CHECKING:
  from .node_fills import NodeFill

T = TypeVar('T')

TradesSource = Literal['indexer', 'node', 'fastest']
"""Where `trades_stream` reads fills from. See `Settings.trades_source`."""


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
  trades_source: TradesSource
  """Where `trades_stream` reads fills from. Defaults to `'indexer'`.

  - `'indexer'`: the indexer's `v4_subaccounts` WebSocket channel.
  - `'node'`: the account's full node (`full_node_grpc`/`full_node_rpc` on
    `accounts.Dydx`) only, about 0.4 s ahead of the indexer: its gRPC
    `StreamOrderbookUpdates` stream, finalized updates only. Fills of our orders and
    fills liquidating us come from the stream; deleveraging fills also read the block's
    `match` events (`block_results`) for side and price. `time` is the local receive
    time (the stream has no block time), `id` is synthetic
    (`<height>:<order id or subaccount:kind:perpetual>:<n>`) and `fee` is `None`. There
    is no fallback: fills finalized while the node is unreachable are missed, so the
    caller's reconciliation (e.g. `trades_history`) must cover them.
  - `'fastest'`: `'node'` and `'indexer'` raced. Each fill is emitted once, by whichever
    source delivers it first (`details['source']`), so the indexer covers node outages.
  """


settings_adapter = pydantic.TypeAdapter(Settings)


@dataclass(kw_only=True)
class Shared(SDK):
  client: Dydx
  parent_subaccount: int = 0
  address: str | None
  venue_id: Literal['dydx', 'dydx_testnet'] = 'dydx'
  """The network this client is connected to, as a venue ID."""
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
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
  full_node: Chain | None = None
  """Chain client of the account's own full node: its gRPC streams fills
  (`StreamOrderbookUpdates`) and its CometBFT RPC serves `block_results` for
  deleveraging fills. Separate from `client.chain`, the public endpoints."""
  node_subscription: 'Subscription[NodeFill] | None' = None
  """The full node fill feed, created by the first node-sourced `trades_stream`."""

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

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own client with the venue's entry and cleanup policies."""
    return ManagedResource(
      resource=self.client,
      wrap_enter=wrap_exceptions,
      wrap_exit=wrap_exceptions,
    )

  @cached_property
  def full_node_resource(self) -> ManagedResource[object] | None:
    """Own the full node's chain client, when configured."""
    if self.full_node is None:
      return None
    return ManagedResource(
      resource=self.full_node, wrap_enter=wrap_exceptions, wrap_exit=wrap_exceptions
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.client_resource
    if self.full_node_resource is not None:
      yield self.full_node_resource


FULL_NODE_GRPC_PORT = 9090
"""Default gRPC port of a dYdX full node."""


def full_node_chain(*, grpc: str, rpc: str) -> Chain:
  """A chain client of one full node.

  Args:
    grpc: Plaintext gRPC `host:port`; the port defaults to 9090.
    rpc: CometBFT RPC URL.
  """
  host, sep, port = grpc.rpartition(':')
  if not sep or not port.isdigit():
    host, port = grpc, str(FULL_NODE_GRPC_PORT)
  return Chain.new(
    GrpcClient(host=host, port=int(port), ssl=False),
    chain_comet_client=CometClient(base_url=rpc.rstrip('/')),
  )


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
    *,
    mnemonic: str | None = None,
    private_key: str | None = None,
    public: bool = False,
    address: str | None = None,
    mainnet: bool = True,
    validate: bool = True,
    parent_subaccount: int = 0,
    account_id: str | None = None,
    full_node_grpc: str | None = None,
    full_node_rpc: str | None = None,
  ):
    """Create a surface over a new client.

    Args:
      mnemonic: Account mnemonic.
      private_key: Account or API wallet private key.
      public: Allow credential-free usage for public data.
      address: Account address; derived from the wallet when omitted.
      mainnet: Use mainnet when true, testnet when false.
      validate: Validate indexer responses.
      parent_subaccount: Parent subaccount number.
      account_id: Root SDK account key, the first segment of every ID; defaults to
        the venue ID.
      full_node_grpc: `host:port` of a full node's gRPC streaming endpoint, for the
        `'node'` and `'fastest'` trades sources (with `full_node_rpc`).
      full_node_rpc: The same node's CometBFT RPC URL, read for deleveraging fills.
    """
    client = (
      Dydx.mainnet(
        mnemonic,
        private_key=private_key,
        address=address,
        indexer={'validate': validate},
        public=public,
      )
      if mainnet
      else Dydx.testnet(
        mnemonic,
        private_key=private_key,
        address=address,
        indexer={'validate': validate},
        public=public,
      )
    )
    if address is None and client.node.wallet is not None:
      address = client.node.require_wallet().address
    return cls(
      shared=Shared(
        client=client,
        address=address,
        parent_subaccount=parent_subaccount,
        venue_id='dydx' if mainnet else 'dydx_testnet',
        account_id=account_id,
        full_node=(
          full_node_chain(grpc=full_node_grpc, rpc=full_node_rpc)
          if full_node_grpc is not None and full_node_rpc is not None
          else None
        ),
      )
    )

  @property
  def venue_id(self) -> Literal['dydx', 'dydx_testnet']:
    """The venue this object trades on: `'dydx'` or `'dydx_testnet'`."""
    return self.shared.venue_id

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.shared.venue_id

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
