from typing_extensions import TypedDict, Literal, NotRequired
from dataclasses import dataclass, field
import asyncio
import os

from trading_sdk.core import SDK, Stream, Subscription

from hyperliquid import Hyperliquid, Wallet
from hyperliquid.info.spot.spot_meta import SpotMetaResponse, SpotAssetInfo, SpotTokenInfo
from hyperliquid.info.methods.user_fees import UserFeesResponse
from hyperliquid.info.perps.perp_meta_and_asset_ctxs import (
  PerpMeta as PerpMetaResponse,
  PerpAssetCtx,
  PerpAssetInfo,
)
from hyperliquid.info.perps.perp_dexs import PerpDex
from hyperliquid.streams.user_fills import WsUserFills
from hyperliquid.streams.l2_book import L2BookData

from hyperliquid_sdk.core import Settings, wrap_exceptions

class DEX(TypedDict):
  name: str
  idx: int

class SpotMeta(TypedDict):
  asset_meta: SpotAssetInfo
  base_meta: SpotTokenInfo
  quote_meta: SpotTokenInfo

class PerpMeta(TypedDict):
  asset_idx: int
  asset_meta: PerpAssetInfo
  collateral_meta: SpotTokenInfo

def find_asset_idx(name: str, perp_meta: PerpMetaResponse) -> int:
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
  pos = next((i for i, a in enumerate(spot_meta['universe']) if a['index'] == spot_index), None)
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


@dataclass(kw_only=True)
class Shared:
  client: Hyperliquid
  address: str
  settings: Settings = field(default_factory=Settings)

  # Cached meta (venue-wide).
  spot_meta: SpotMetaResponse | None = None
  # Lightweight DEX directory: idx -> PerpDex | None (wire type allows None entries).
  perp_dexs: dict[int, PerpDex | None] | None = None
  # Perp meta keyed by dex index; None key is used for the 'no dex' case.
  perp_metas: dict[int | None, PerpMetaResponse] = field(default_factory=dict)
  perp_asset_ctxs: dict[int | None, list[PerpAssetCtx]] = field(default_factory=dict)
  user_fees: UserFeesResponse | None = None

  # Stream subscriptions.
  user_fills_subscription: Subscription[WsUserFills] | None = None
  l2_book_subscriptions: dict[str, Subscription[L2BookData]] = field(default_factory=dict)

  # Locks for concurrent lazy loads.
  _spot_meta_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
  _perp_meta_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
  _fees_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

  @wrap_exceptions
  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  @wrap_exceptions
  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)

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
  ) -> tuple[int, PerpMetaResponse, list[PerpAssetCtx]]:
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
      perp_meta, asset_ctxs = await self.client.info.perp_meta_and_asset_ctxs(dex_name)
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
      self.user_fees = await self.client.info.user_fees(self.address)
      return self.user_fees

  async def resolve_dex_idx(self, dex_name: str | None, *, refetch: bool = False) -> int:
    """
    Convenience wrapper that just returns the dex index for a given dex name.
    Uses the same caching as `load_perp_meta_for_dex`.
    """
    idx, _, _ = await self.load_perp_meta_for_dex(dex_name, refetch=refetch)
    return idx

  def user_fills_sub(self) -> Subscription[WsUserFills]:
    if self.user_fills_subscription is None:
      async def subscribe_user_fills() -> Stream[WsUserFills]:
        stream = await self.client.streams.user_fills(self.address, aggregate_by_time=True)
        return Stream(stream, stream.unsubscribe)
      self.user_fills_subscription = Subscription.of(subscribe_user_fills)
    return self.user_fills_subscription

  def l2_book_subscription(self, coin: str, /) -> Subscription[L2BookData]:
    if coin not in self.l2_book_subscriptions:
      async def subscribe() -> Stream[L2BookData]:
        stream = await self.client.streams.l2_book(coin)
        return Stream(stream, stream.unsubscribe)
      self.l2_book_subscriptions[coin] = Subscription.of(subscribe)
    return self.l2_book_subscriptions[coin]

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
class SharedMixin:
  shared: Shared

  @classmethod
  def http(
    cls, address: str | None = None, *, wallet: Wallet | None = None,
    mainnet: bool = True, validate: bool = True, settings: Settings = {}
  ):
    if address is None:
      address = os.environ['HYPERLIQUID_ADDRESS'] if mainnet else os.environ['HYPERLIQUID_TESTNET_ADDRESS']
    client = Hyperliquid.http(wallet, mainnet=mainnet, validate=validate)
    return cls(shared=Shared(client=client, address=address, settings=settings))

  @classmethod
  def ws(
    cls, address: str | None = None, *, wallet: Wallet | None = None,
    mainnet: bool = True, validate: bool = True, settings: Settings = {}
  ):
    if address is None:
      address = os.environ['HYPERLIQUID_ADDRESS']
    client = Hyperliquid.ws(wallet, mainnet=mainnet, validate=validate)
    return cls(shared=Shared(client=client, address=address, settings=settings))

  @property
  def client(self) -> Hyperliquid:
    return self.shared.client

  @property
  def address(self) -> str:
    return self.shared.address

  @property
  def settings(self) -> Settings:
    return self.shared.settings

  @property
  def index_price(self) -> Literal['oracle', 'mark']:
    return self.settings.get('index_price', 'oracle')

  async def __aenter__(self):
    await self.shared.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.shared.__aexit__(exc_type, exc_value, traceback)

  async def subscribe_user_fills(self) -> Stream[WsUserFills]:
    return await self.shared.user_fills_sub().subscribe()

  async def subscribe_l2_book(self, coin: str, /) -> Stream[L2BookData]:
    return await self.shared.l2_book_subscription(coin).subscribe()


@dataclass(kw_only=True, frozen=True)
class SpotMixin(SharedMixin):
  ...


@dataclass(kw_only=True, frozen=True)
class SpotMarketMixin(SDK, SpotMixin):
  meta: SpotMeta

  @property
  def asset_idx(self) -> int:
    return self.meta['asset_meta']['index']

  @property
  def asset_meta(self) -> SpotAssetInfo:
    return self.meta['asset_meta']

  @property
  def asset_name(self) -> str:
    return self.asset_meta['name']

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
    if dex: # we treat '' and None equivalently
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
class PerpMarketMixin(SDK, PerpMixin):
  meta: PerpMeta

  @property
  def asset_idx(self) -> int:
    return self.meta['asset_idx']

  @property
  def asset_meta(self) -> PerpAssetInfo:
    return self.meta['asset_meta']

  @property
  def asset_name(self) -> str:
    return self.asset_meta['name']

  @property
  def collateral_meta(self) -> SpotTokenInfo:
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

