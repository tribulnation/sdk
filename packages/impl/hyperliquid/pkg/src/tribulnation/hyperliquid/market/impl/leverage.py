"""Account leverage on perpetual markets, the opening capacity it implies, and the venue's position limits."""

from datetime import timedelta
from decimal import Decimal
import asyncio

from typed_hyperliquid.info.active_asset_data import ActiveAssetData
from typed_hyperliquid.info.clearinghouse_state import ClearinghouseState
from typed_hyperliquid.info.perp_meta_and_asset_ctxs import (
  PerpDexMeta,
  PerpUniverseAsset,
)

from tribulnation.sdk.market import PositionHeadroom
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


def tier_limit(
  meta: PerpDexMeta, asset: PerpUniverseAsset, *, leverage: Decimal
) -> Decimal | None:
  """The most position notional the asset's margin table allows at `leverage`.

  A tier's `maxLeverage` applies from its `lowerBound` up, so the position may grow
  up to the first tier that no longer allows `leverage`; beyond it Hyperliquid refuses
  orders with `PerpMaxPosition`. `None` when every tier allows it, or the asset's
  table is not listed (ids below 50 are single-tier tables at `maxLeverage`).
  """
  tables = dict(meta['marginTables'])
  if (table := tables.get(asset.get('marginTableId', -1))) is not None:
    bounds = [
      t['lowerBound'] for t in table['marginTiers'] if t['maxLeverage'] < leverage
    ]
    return min(bounds, default=None)


def held_position(
  state: ClearinghouseState, coin: str
) -> tuple[Decimal, Decimal | None]:
  """The signed notional of the position in `coin` (`positionValue`, positive long) and its leverage; 0 and None when flat."""
  for entry in state['assetPositions']:
    pos = entry['position']
    if pos['coin'] == coin:
      value = pos['positionValue'] if pos['szi'] >= 0 else -pos['positionValue']
      return value, Decimal(pos['leverage']['value'])
  return Decimal(0), None


def capped(coin: str, capped_coins: frozenset[str]) -> bool:
  """Whether `coin` (`dex:`-prefixed off the default dex) is listed at its open-interest cap, prefixed or not."""
  return coin in capped_coins or coin.partition(':')[2] in capped_coins


@wrap_exceptions
async def perp_position_headroom(
  self: PerpMarketMixin, *, ttl: timedelta | None = None
) -> PositionHeadroom:
  """Nothing while the coin is at its open-interest cap, else the margin tier limit's room.

  `perpsAtOpenInterestCap` lists coins where only reducing orders are accepted, so
  neither direction may grow. Otherwise the margin table bounds the position's
  notional at its leverage (`tier_limit`); without such a bound the headroom is
  unknown (`None`). Hyperliquid's own per-user figures
  (`activeAssetData.maxTradeSzs`) also count free margin, which
  `available_notional()` covers, so they are not used here.

  Costs two reads shared by every coin of the dex (`ttl`): `perpsAtOpenInterestCap`
  and `clearinghouseState`. The leverage is the open position's; a flat coin is
  bounded at the asset's `maxLeverage`, the tightest tier limit any setting has, rather
  than reading the setting (`activeAssetData`) one coin per request.
  """
  coin = self.asset_name
  capped_coins, (_, meta, _), state = await asyncio.gather(
    self.shared.perps_at_open_interest_cap(self.dex_name, ttl=ttl),
    self.shared.load_perp_meta_for_dex(self.dex_name),
    self.shared.clearinghouse_state(self.dex_name, ttl=ttl),
  )
  if capped(coin, capped_coins):
    return PositionHeadroom(long=Decimal(0), short=Decimal(0))
  else:
    asset = meta['universe'][find_asset_idx(coin, meta)]
    position, leverage = held_position(state, coin)
    return PositionHeadroom.capped(
      max_notional=tier_limit(
        meta, asset, leverage=leverage or Decimal(asset['maxLeverage'])
      ),
      position=position,
    )
