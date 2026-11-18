"""Account leverage on perpetual markets and the opening capacity it implies."""

from datetime import timedelta
from decimal import Decimal
import asyncio

from typed_hyperliquid.info.active_asset_data import ActiveAssetData
from typed_hyperliquid.info.perp_meta_and_asset_ctxs import PerpUniverseAsset

from tribulnation.sdk.util import whole_leverage

from tribulnation.hyperliquid.core import wrap_exceptions
from .collateral import spot_collateral
from .mixin import PerpMarketMixin, find_asset_idx


def parse_leverage(data: ActiveAssetData, *, max_leverage: int) -> Decimal:
  """The account's leverage setting for an asset, capped at its `maxLeverage`.

  Cross and isolated settings mean the same multiple: opening `n` of notional takes
  `n / value` of margin from the account's free collateral. Without a usable setting
  the asset's `maxLeverage` applies. Hyperliquid reports its default setting for
  assets the account never configured, so that fallback is defensive.

  Args:
    data: The `activeAssetData` response for the account and coin.
    max_leverage: The asset's `maxLeverage` from the perpetual universe.
  """
  setting = data.get('leverage')
  value = setting.get('value') if setting is not None else None
  if value is None or value <= 0:
    return Decimal(max_leverage)
  return Decimal(min(value, max_leverage))


@wrap_exceptions
async def perp_leverage(
  self: PerpMarketMixin, *, ttl: timedelta | None = None
) -> Decimal:
  """The account's leverage on this market, from a shared `activeAssetData` read.

  `maxLeverage` comes from the cached dex universe, which `rules(refetch=True)` reloads.
  """
  coin = self.asset_name
  _, perp_meta, _ = await self.shared.load_perp_meta_for_dex(self.dex_name)
  asset = perp_meta['universe'][find_asset_idx(coin, perp_meta)]
  data = await self.shared.active_asset_data(coin, ttl=ttl)
  return parse_leverage(data, max_leverage=asset['maxLeverage'])


def cross_allowed(asset: PerpUniverseAsset) -> bool:
  """Whether the asset may trade on cross margin (HIP-3 markets may be isolated-only)."""
  return not asset.get('onlyIsolated') and asset.get('marginMode') != 'noCross'


@wrap_exceptions
async def set_perp_leverage(self: PerpMarketMixin, leverage: Decimal):
  """Set the account's leverage on this market (`updateLeverage`), keeping its mode.

  Cross, unless the account's setting on the asset is isolated or the asset allows
  isolated margin only. The shared `activeAssetData` answer is dropped, so the next
  `leverage()` reads the new setting.

  Raises:
    ValueError: `leverage` is not a positive whole number.
  """
  value = whole_leverage(leverage)
  coin = self.asset_name
  data = await self.shared.active_asset_data(coin, ttl=None)
  setting = data.get('leverage')
  isolated = setting is not None and setting['type'] == 'isolated'
  await self.client.exchange.update_leverage(
    asset=self.asset_id,
    is_cross=cross_allowed(self.asset_meta) and not isolated,
    leverage=value,
  )
  self.shared.forget_active_asset_data(coin)


@wrap_exceptions
async def perp_available_notional(
  self: PerpMarketMixin, *, ttl: timedelta | None = None
) -> Decimal:
  """Free unified collateral times the account's leverage on this market.

  Both cross and isolated positions are opened from the collateral token's free spot
  balance (`total - hold`, see `spot_collateral`), not from an isolated position's
  own bucket, so this reads the account pool whatever the market's margin mode.
  """
  leverage, state = await asyncio.gather(
    perp_leverage(self, ttl=ttl), self.shared.spot_clearinghouse_state(ttl=ttl)
  )
  _, free = spot_collateral(state, self.collateral_meta['index'])
  return free * leverage
