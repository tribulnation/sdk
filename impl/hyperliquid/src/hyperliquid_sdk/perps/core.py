from typing_extensions import TypedDict, NotRequired, Literal
from dataclasses import dataclass

from hyperliquid_sdk.core import Mixin
from hyperliquid.info.spot.spot_meta import SpotTokenInfo, SpotMetaResponse
from hyperliquid.info.perps.perp_meta_and_asset_ctxs import PerpAssetInfo, PerpMeta

class DEX(TypedDict):
  name: str
  idx: int

class Meta(TypedDict):
  dex: NotRequired[DEX|None]
  asset_idx: int
  asset_meta: PerpAssetInfo
  collateral_meta: SpotTokenInfo
  index_price: Literal['oracle', 'mark']
  """Which price source to use for the index price. See the [docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/robust-price-indices) for details."""

@dataclass(kw_only=True, frozen=True)
class PerpMixin(Mixin):
  meta: Meta

  @classmethod
  def of(cls, other: 'PerpMixin'):
    return cls(
      address=other.address,
      client=other.client,
      settings=other.settings,
      streams=other.streams,
      meta=other.meta,
    )

  @classmethod
  def meta_of(
    cls, asset_idx: int, /, *, perp_meta: PerpMeta, spot_meta: SpotMetaResponse,
    dex: DEX | None = None, index_price: Literal['oracle', 'mark'] = 'mark',
  ) -> Meta:
    asset_meta = perp_meta['universe'][asset_idx]
    collateral_idx = perp_meta['collateralToken']
    return {
      'dex': dex,
      'asset_idx': asset_idx,
      'asset_meta': asset_meta,
      'collateral_meta': spot_meta['tokens'][collateral_idx],
      'index_price': index_price,
    }

  @property
  def dex(self) -> str | None:
    if (dex := self.meta.get('dex')) is not None:
      return dex['name']

  @property
  def dex_idx(self) -> int | None:
    if (dex := self.meta.get('dex')) is not None:
      return dex['idx']

  @property
  def asset_idx(self) -> int:
    return self.meta['asset_idx']

  @property
  def asset_id(self) -> int:
    """Non-scoped asset index, used for placing orders. See the [docs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids) for details."""
    if (dex := self.dex_idx) is None:
      return self.asset_idx
    else:
      return 100000 + dex * 10000 + self.asset_idx

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
  def index_price(self) -> Literal['oracle', 'mark']:
    return self.meta['index_price']
