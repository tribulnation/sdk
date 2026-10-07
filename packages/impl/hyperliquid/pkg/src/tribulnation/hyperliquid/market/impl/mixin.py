from functools import cached_property
from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  AsyncGenerator,
  Awaitable,
  Callable,
  Iterable,
  TypedDict,
  TypeVar,
  cast,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import asyncio
import os

from tribulnation.sdk.core import ManagedResource, SDK, Subscription, OverflowPolicy

from typed_hyperliquid import Hyperliquid, Wallet
from typed_hyperliquid.core.ws import SocketClient
from typed_hyperliquid.streams import Streams
from typed_hyperliquid.info.spot_meta import (
  SpotMeta as SpotMetaResponse,
  SpotPair,
  SpotToken,
)
from typed_hyperliquid.info.user_fees import FeeSchedule, UserFeesResponse
from typed_hyperliquid.info.perp_meta_and_asset_ctxs import (
  PerpDexMeta,
  PerpAssetContext,
  PerpUniverseAsset,
)
from typed_hyperliquid.info.perp_dexs import PerpDex
from typed_hyperliquid.streams.user_fills import UserFills
from typed_hyperliquid.streams.l2_book import L2BookUpdate
from typed_hyperliquid.streams.bbo import BboLevel0, BboLevel1
from typed_hyperliquid.core import TimestampMillis
from typed_core.validation import validator

from tribulnation.hyperliquid.core import DepthSource, Settings, wrap_exceptions

T = TypeVar('T')


class BboUpdate(TypedDict):
  """A `bbo` push. Unlike the client's `WsBbo`, a side may be `null` when it is empty."""

  coin: str
  bbo: tuple[BboLevel0 | None, BboLevel1 | None]
  """Best bid and ask, as `[bid, ask]`; `None` for an empty side."""
  time: TimestampMillis
  """Update timestamp, epoch milliseconds."""


DepthMessage = L2BookUpdate | BboUpdate
"""A raw depth push: an `l2Book` snapshot (`'l2'`/`'fast'`) or a `bbo` update."""


class DEX(TypedDict):
  name: str
  idx: int


class SpotMeta(TypedDict):
  asset_meta: SpotPair
  base_meta: SpotToken
  quote_meta: SpotToken


class PerpMeta(TypedDict):
  asset_idx: int
  asset_meta: PerpUniverseAsset
  collateral_meta: SpotToken


def find_asset_idx(name: str, perp_meta: PerpDexMeta) -> int:
  for idx, asset in enumerate(perp_meta['universe']):
    if asset['name'] == name:
      return idx
  raise ValueError(f'Perp {name} not found')


def find_dex_idx(name: str, dexs: list[PerpDex | None]) -> int:
  for idx, obj in enumerate(dexs):
    if obj and obj['name'] == name:
      return idx
  raise ValueError(f'DEX {name} not found')


def spot_meta_of(spot_index: int, /, *, spot_meta: SpotMetaResponse) -> SpotMeta:
  # Canonical spot id uses `spotMeta.universe[].index`.
  pos = next(
    (i for i, a in enumerate(spot_meta['universe']) if a['index'] == spot_index), None
  )
  if pos is None:
    raise ValueError(f'Spot index {spot_index} not found in spot_meta universe')
  asset_meta = spot_meta['universe'][pos]
  base_idx, quote_idx = asset_meta['tokens']
  tokens_by_index = {t['index']: t for t in spot_meta['tokens']}
  return {
    'asset_meta': asset_meta,
    'base_meta': tokens_by_index[base_idx],
    'quote_meta': tokens_by_index[quote_idx],
  }


@wrap_exceptions
async def translated(stream: AsyncIterable[T]) -> AsyncGenerator[T]:
  """Iterate `stream`, re-raising client errors (e.g. a dropped socket) as SDK errors."""
  async for item in stream:
    yield item


@wrap_exceptions
async def bbo_updates(
  stream: AsyncIterable[object], *, validate: bool
) -> AsyncGenerator[BboUpdate]:
  """Iterate raw `bbo` pushes as `BboUpdate`s, translating client errors.

  Args:
    stream: The client's `bbo` stream, subscribed without its own validation.
    validate: Validate each push against `BboUpdate`; otherwise pass it through as is.
  """
  check = validator(BboUpdate).python
  async for item in stream:
    yield check(item) if validate else cast(BboUpdate, item)


@asynccontextmanager
async def closing_fast_streams(shared: 'Shared'):
  """Close the dedicated `'fast'` connection at exit, if a subscription ever opened it.

  Checked only on exit, so a connection created lazily inside the block is still
  closed; one never created is never dialled.
  """
  try:
    yield shared
  finally:
    if (streams := shared.fast_streams) is not None:
      shared.fast_streams = None
      # The client's `__aexit__` leaves its parameters unannotated.
      socket = cast(AsyncContextManager[object], streams.client)
      await socket.__aexit__(None, None, None)


@dataclass(kw_only=True)
class Shared(SDK):
  client: Hyperliquid
  maybe_address: str | None = None

  @property
  def address(self) -> str:
    if self.maybe_address is None:
      raise ValueError('Address must be provided')
    return self.maybe_address

  # Cached meta (venue-wide).
  spot_meta: SpotMetaResponse | None = None
  # Lightweight DEX directory: idx -> PerpDex | None (wire type allows None entries).
  perp_dexs: dict[int, PerpDex | None] | None = None
  # Perp meta keyed by dex index; None key is used for the 'no dex' case.
  perp_metas: dict[int | None, PerpDexMeta] = field(
    default_factory=dict[int | None, PerpDexMeta]
  )
  perp_asset_ctxs: dict[int | None, list[PerpAssetContext]] = field(
    default_factory=dict[int | None, list[PerpAssetContext]]
  )
  user_fees: UserFeesResponse | None = None
  standard_fee_schedule: FeeSchedule | None = None

  # Stream subscriptions.
  user_fills_subscription: Subscription[UserFills] | None = None
  depth_subscriptions: dict[tuple[str, DepthSource], Subscription[DepthMessage]] = (
    field(default_factory=dict[tuple[str, DepthSource], Subscription[DepthMessage]])
  )
  """Upstream depth feeds keyed by `(coin, source)`, each fanned out to its consumers."""
  fast_streams: Streams | None = None
  """Streams over the dedicated `'fast'` connection; `None` until first needed."""

  # Locks for concurrent lazy loads.
  _spot_meta_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )
  _perp_meta_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )
  _fees_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own client with the venue's entry and cleanup policies."""
    return ManagedResource(
      resource=self.client,
      wrap_enter=wrap_exceptions,
      wrap_exit=wrap_exceptions,
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.client_resource
    yield ManagedResource(
      resource=closing_fast_streams(self),
      wrap_enter=wrap_exceptions,
      wrap_exit=wrap_exceptions,
    )

  def fast_streams_client(self) -> Streams:
    """The dedicated `'fast'` connection's streams, created on first use.

    Hyperliquid tags `l2Book` pushes with the coin only, not the `fast` flag, so one
    connection subscribed to both variants of a coin cannot route them apart. `'fast'`
    subscriptions therefore live on their own socket, copied from the main one's
    settings. It connects lazily on the first subscribe and is closed with `Shared`.
    """
    if self.fast_streams is None:
      main = self.client.streams_client
      socket = SocketClient(
        url=main.url, timeout=main.timeout, ping_interval=main.ping_interval
      )
      self.fast_streams = Streams.new(socket, validate=self.client.validate)
    return self.fast_streams

  @wrap_exceptions
  async def load_spot_meta(self, *, refetch: bool = False) -> SpotMetaResponse:
    if not refetch and self.spot_meta is not None:
      return self.spot_meta
    async with self._spot_meta_lock:
      if not refetch and self.spot_meta is not None:
        return self.spot_meta
      self.spot_meta = await self.client.info.spot_meta()
      return self.spot_meta

  @wrap_exceptions
  async def load_perp_dexs(self, *, refetch: bool = False) -> dict[int, PerpDex | None]:
    """
    Load and cache the list of DEXs (lightweight). Keyed by dex index.
    """
    if not refetch and self.perp_dexs is not None:
      return self.perp_dexs
    # No separate lock; cost is small and we typically call this rarely.
    dexs = await self.client.info.perp_dexs()
    self.perp_dexs = {idx: dex for idx, dex in enumerate(dexs)}
    return self.perp_dexs

  @wrap_exceptions
  async def load_perp_meta_for_dex(
    self,
    dex_name: str | None,
    *,
    refetch: bool = False,
  ) -> tuple[int, PerpDexMeta, list[PerpAssetContext]]:
    """
    Load perp meta + asset ctxs for a given dex name, caching per dex index.
    `dex_name = None` uses the default/no-dex universe.
    """
    if dex_name is None:
      dex_idx = 0
    else:
      dexs = await self.load_perp_dexs()
      dex_idx = find_dex_idx(dex_name, list(dexs.values()))

    key = dex_idx
    if not refetch and key in self.perp_metas and key in self.perp_asset_ctxs:
      return key, self.perp_metas[key], self.perp_asset_ctxs[key]
    async with self._perp_meta_lock:
      if not refetch and key in self.perp_metas and key in self.perp_asset_ctxs:
        return key, self.perp_metas[key], self.perp_asset_ctxs[key]
      perp_meta, asset_ctxs = await self.client.info.perp_meta_and_asset_ctxs(
        dex=dex_name,
      )
      self.perp_metas[key] = perp_meta
      self.perp_asset_ctxs[key] = asset_ctxs
      return key, perp_meta, asset_ctxs

  @wrap_exceptions
  async def load_user_fees(self, *, refetch: bool = False) -> UserFeesResponse:
    if not refetch and self.user_fees is not None:
      return self.user_fees
    async with self._fees_lock:
      if not refetch and self.user_fees is not None:
        return self.user_fees
      self.user_fees = await self.client.info.user_fees(user=self.address)
      return self.user_fees

  @wrap_exceptions
  async def load_standard_fee_schedule(self, *, refetch: bool = False) -> FeeSchedule:
    """Read only the public schedule, using a fixed non-account lookup address."""
    if self.standard_fee_schedule is None or refetch:
      response = await self.client.info.user_fees(user='0x' + '0' * 40)
      self.standard_fee_schedule = response['feeSchedule']
    return self.standard_fee_schedule

  async def resolve_dex_idx(
    self, dex_name: str | None, *, refetch: bool = False
  ) -> int:
    """
    Convenience wrapper that just returns the dex index for a given dex name.
    Uses the same caching as `load_perp_meta_for_dex`.
    """
    idx, _, _ = await self.load_perp_meta_for_dex(dex_name, refetch=refetch)
    return idx

  def user_fills_sub(self) -> Subscription[UserFills]:
    if self.user_fills_subscription is None:

      async def subscribe_user_fills():
        stream = await self.client.streams.user_fills(
          self.address, aggregate_by_time=True
        )
        return stream, stream.unsubscribe

      self.user_fills_subscription = Subscription.of(subscribe_user_fills)
    return self.user_fills_subscription

  def depth_subscription(
    self, coin: str, source: DepthSource, /
  ) -> Subscription[DepthMessage]:
    """The shared upstream for `coin`'s `source` feed, one per `(coin, source)`.

    Args:
      coin: Hyperliquid coin name, e.g. `ETH`, `@107` or `dex:ASSET`.
      source: Which feed; see `Settings.depth_source`.
    """
    key = (coin, source)
    if key not in self.depth_subscriptions:

      @wrap_exceptions
      async def subscribe():
        """Open the upstream feed for `key` on the connection that serves it."""
        if source == 'bbo':
          # Validated here, not by the client: its `WsBbo` rejects an empty (`null`) side.
          raw = await self.client.streams.bbo(coin, validate=False)
          return Subscription.Context[DepthMessage](
            bbo_updates(raw, validate=self.client.validate), raw.unsubscribe
          )
        if source == 'fast':
          stream = await self.fast_streams_client().l2_book(coin, fast=True)
        else:
          stream = await self.client.streams.l2_book(coin)
        return Subscription.Context[DepthMessage](
          translated(stream), stream.unsubscribe
        )

      self.depth_subscriptions[key] = Subscription(subscribe)
    return self.depth_subscriptions[key]

  @wrap_exceptions
  async def spot_meta_of(
    self,
    spot_index: int,
    /,
    *,
    refetch: bool = False,
  ) -> SpotMeta:
    spot_meta = await self.load_spot_meta(refetch=refetch)
    return spot_meta_of(spot_index, spot_meta=spot_meta)

  @wrap_exceptions
  async def resolve_asset_index(self, name: str, /, *, refetch: bool = False) -> str:
    """Resolve a token name to its index, falling back to the raw name if unknown.

    `Rules`/`Trade.fee` need a raw asset identifier that agrees with the rest of the
    SDK's Hyperliquid surface (report/history/assets.py resolves the same way, for the
    same reason: `Snapshots` keys balances by numeric token index, not name — see that
    module's docstring). Unlike `base_name`/`quote_name`/`asset_name` on the mixins below,
    which stay name-based on purpose (matching a fill's raw `coin` field, building a
    human-readable market id), this is only for values handed to the caller as data.
    """
    spot_meta = await self.load_spot_meta(refetch=refetch)
    for token in spot_meta['tokens']:
      if token['name'] == name:
        return str(token['index'])
    return name

  @wrap_exceptions
  async def perp_meta_of(
    self,
    market: str,
    /,
    *,
    dex_name: str | None,
    refetch: bool = False,
  ) -> PerpMeta:
    spot_meta = await self.load_spot_meta(refetch=refetch)
    dex_idx, perp_meta, _ = await self.load_perp_meta_for_dex(dex_name, refetch=refetch)

    asset_idx = find_asset_idx(market, perp_meta)
    collateral_idx = perp_meta['collateralToken']
    tokens_by_index = {t['index']: t for t in spot_meta['tokens']}

    return PerpMeta(
      asset_idx=asset_idx,
      asset_meta=perp_meta['universe'][asset_idx],
      collateral_meta=tokens_by_index[collateral_idx],
    )


@dataclass(frozen=True)
class SharedMixin(SDK):
  shared: Shared

  @SDK.method
  @wrap_exceptions
  async def call_hyperliquid(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Run one retriable request without restarting an entire history walk."""
    return await fn()

  @classmethod
  def http(
    cls,
    address: str | None = None,
    *,
    wallet: Wallet | None = None,
    mainnet: bool = True,
    validate: bool = True,
  ):
    if address is None:
      env_var = 'HYPERLIQUID_ADDRESS' if mainnet else 'HYPERLIQUID_TESTNET_ADDRESS'
      address = os.environ.get(env_var)
    client = Hyperliquid.new(
      wallet,
      mainnet=mainnet,
      validate=validate,
      public=True,
    )
    return cls(shared=Shared(client=client, maybe_address=address))

  @classmethod
  def ws(
    cls,
    address: str | None = None,
    *,
    wallet: Wallet | None = None,
    mainnet: bool = True,
    validate: bool = True,
    public: bool = False,
  ):
    if address is None:
      env_var = 'HYPERLIQUID_ADDRESS' if mainnet else 'HYPERLIQUID_TESTNET_ADDRESS'
      address = os.environ.get(env_var)
    client = Hyperliquid.new(
      wallet,
      mainnet=mainnet,
      validate=validate,
      public=True,
    )
    return cls(shared=Shared(client=client, maybe_address=address))

  @property
  def client(self) -> Hyperliquid:
    return self.shared.client

  @property
  def address(self) -> str:
    return self.shared.address

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.shared

  def subscribe_user_fills(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    return self.shared.user_fills_sub().subscribe(
      queue_size=queue_size, overflow=overflow
    )

  def subscribe_depth(
    self,
    coin: str,
    source: DepthSource,
    /,
    *,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ):
    """Subscribe to the shared `(coin, source)` depth feed through a bounded inbox."""
    return self.shared.depth_subscription(coin, source).subscribe(
      queue_size=queue_size, overflow=overflow
    )


@dataclass(kw_only=True, frozen=True)
class SpotMixin(SharedMixin): ...


@dataclass(kw_only=True, frozen=True)
class SpotMarketMixin(SpotMixin):
  meta: SpotMeta

  @property
  def asset_idx(self) -> int:
    return self.meta['asset_meta']['index']

  @property
  def asset_meta(self) -> SpotPair:
    return self.meta['asset_meta']

  @property
  def asset_name(self) -> str:
    return self.asset_meta['name']

  @property
  def base_meta(self):
    return self.meta['base_meta']

  @property
  def quote_meta(self):
    return self.meta['quote_meta']

  @property
  def base_name(self) -> str:
    return self.meta['base_meta']['name']

  @property
  def quote_name(self) -> str:
    return self.meta['quote_meta']['name']

  @property
  def asset_id(self) -> int:
    return 10000 + self.asset_idx


@dataclass(kw_only=True, frozen=True)
class PerpMixin(SharedMixin):
  dex: DEX | None

  @classmethod
  async def fetch(cls, shared: Shared, *, dex: str | None = None):
    if dex:  # we treat '' and None equivalently
      dex_idx = await shared.resolve_dex_idx(dex)
      dex_obj: DEX | None = {'name': dex, 'idx': dex_idx}
    else:
      dex_obj = None
    return cls(shared, dex=dex_obj)

  @property
  def dex_idx(self) -> int | None:
    if self.dex is not None:
      return self.dex['idx']

  @property
  def dex_name(self) -> str | None:
    if self.dex is not None:
      return self.dex['name']


@dataclass(kw_only=True, frozen=True)
class PerpMarketMixin(PerpMixin):
  meta: PerpMeta

  @property
  def asset_idx(self) -> int:
    return self.meta['asset_idx']

  @property
  def asset_meta(self) -> PerpUniverseAsset:
    return self.meta['asset_meta']

  @property
  def asset_name(self) -> str:
    return self.asset_meta['name']

  @property
  def collateral_meta(self) -> SpotToken:
    return self.meta['collateral_meta']

  @property
  def collateral_name(self) -> str:
    return self.collateral_meta['name']

  @property
  def asset_id(self) -> int:
    # Per docs: base perps use asset index; builder perps use dex-scoped formula.
    if (dex := self.dex_idx) is None:
      return self.asset_idx
    return 100000 + dex * 10000 + self.asset_idx
