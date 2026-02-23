from typing_extensions import TypedDict, NotRequired
from dataclasses import dataclass

from hyperliquid_sdk.core import Mixin, Settings
from hyperliquid.info.spot.spot_meta import SpotAssetInfo, SpotTokenInfo, SpotMetaResponse

class Meta(TypedDict):
  asset_meta: SpotAssetInfo
  base_meta: SpotTokenInfo
  quote_meta: SpotTokenInfo

@dataclass(kw_only=True, frozen=True)
class SpotMixin(Mixin):
  meta: Meta

  @staticmethod
  def meta_of(asset_idx: int, /, *, spot_meta: SpotMetaResponse, ) -> Meta:
    asset_meta = spot_meta['universe'][asset_idx]
    base_idx, quote_idx = asset_meta['tokens']
    return {
      'asset_meta': asset_meta,
      'base_meta': spot_meta['tokens'][base_idx],
      'quote_meta': spot_meta['tokens'][quote_idx],
    }

  @classmethod
  def of(cls, other: 'SpotMixin'):
    return cls(
      address=other.address,
      client=other.client,
      settings=other.settings,
      streams=other.streams,
      meta=other.meta,
    )

  @property
  def asset_idx(self) -> int:
    return self.meta['asset_meta']['index']

  @property
  def asset_id(self) -> int:
    """Used for placing orders. See the [docs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids) for details."""
    return 10000 + self.asset_idx

  @property
  def asset_meta(self) -> SpotAssetInfo:
    return self.meta['asset_meta']

  @property
  def base_meta(self) -> SpotTokenInfo:
    return self.meta['base_meta']

  @property
  def quote_meta(self) -> SpotTokenInfo:
    return self.meta['quote_meta']

  @property
  def asset_name(self) -> str:
    return self.asset_meta['name']

  @property
  def base_name(self) -> str:
    return self.base_meta['name']

  @property
  def quote_name(self) -> str:
    return self.quote_meta['name']