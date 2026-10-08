"""Account leverage on perpetual markets and the opening capacity it implies."""

from decimal import Decimal

from typed_hyperliquid.info.active_asset_data import ActiveAssetData

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
async def perp_leverage(self: PerpMarketMixin, *, refetch: bool = False) -> Decimal:
  """The account's leverage on this market, cached per coin on `Shared`.

  `refetch` also reloads the dex universe, so a changed `maxLeverage` is seen.
  """
  coin = self.asset_name
  cached = self.shared.leverages.get(coin)
  if cached is not None and not refetch:
    return cached
  _, perp_meta, _ = await self.shared.load_perp_meta_for_dex(
    self.dex_name, refetch=refetch
  )
  asset = perp_meta['universe'][find_asset_idx(coin, perp_meta)]
  data = await self.client.info.active_asset_data(user=self.address, coin=coin)
  leverage = parse_leverage(data, max_leverage=asset['maxLeverage'])
  self.shared.leverages[coin] = leverage
  return leverage


@wrap_exceptions
async def perp_available_notional(self: PerpMarketMixin) -> Decimal:
  """Free unified collateral times the account's leverage on this market.

  Both cross and isolated positions are opened from the collateral token's free spot
  balance (`total - hold`, see `spot_collateral`), not from an isolated position's
  own bucket, so this reads the account pool whatever the market's margin mode.
  """
  leverage = await perp_leverage(self)
  state = await self.client.info.spot_clearinghouse_state(user=self.address)
  _, free = spot_collateral(state, self.collateral_meta['index'])
  return free * leverage
