"""Account leverage from `activeAssetData`, its shared reads, and the available notional."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from typing_extensions import Any, cast
from typed_hyperliquid import Hyperliquid
from typed_hyperliquid.info.active_asset_data import ActiveAssetData

from tribulnation.hyperliquid.market.impl.leverage import parse_leverage
from tribulnation.hyperliquid.market.impl.mixin import PerpMeta, Shared
from tribulnation.hyperliquid.market.perps_market import PerpMarket

ADDRESS = '0x' + '1' * 40


def asset_data(leverage: dict[str, Any] | None) -> ActiveAssetData:
  """An `activeAssetData` response carrying only the leverage setting."""
  data: dict[str, Any] = {'user': ADDRESS, 'coin': 'ETC'}
  if leverage is not None:
    data['leverage'] = leverage
  return cast(ActiveAssetData, data)


def test_cross_and_isolated_settings_are_the_leverage():
  """Both margin modes open `n` notional with `n / value` margin."""
  cross = asset_data({'type': 'cross', 'value': 3})
  isolated = asset_data({'type': 'isolated', 'value': 4, 'rawUsd': Decimal(10)})
  assert parse_leverage(cross, max_leverage=5) == 3
  assert parse_leverage(isolated, max_leverage=5) == 4


def test_setting_is_capped_and_missing_setting_falls_back_to_max_leverage():
  """A setting above a lowered `maxLeverage` cannot be opened at; none means the max."""
  assert parse_leverage(asset_data({'type': 'cross', 'value': 20}), max_leverage=5) == 5
  assert parse_leverage(asset_data(None), max_leverage=5) == 5
  assert parse_leverage(asset_data({'type': 'cross', 'value': 0}), max_leverage=5) == 5


def market(
  *, leverage: list[int], dex: str | None = None, hold: str = '20'
) -> tuple[PerpMarket, SimpleNamespace]:
  """A perpetual over a stub client: one `activeAssetData` reply per value."""
  coin = f'{dex}:ETC' if dex else 'ETC'
  asset: dict[str, Any] = {'name': coin, 'maxLeverage': 5, 'szDecimals': 2}
  info = SimpleNamespace(
    active_asset_data=AsyncMock(
      side_effect=[asset_data({'type': 'cross', 'value': v}) for v in leverage]
    ),
    perp_meta_and_asset_ctxs=AsyncMock(
      return_value=({'universe': [asset], 'collateralToken': 0}, [])
    ),
    perp_dexs=AsyncMock(return_value=[None, {'name': dex}]),
    spot_clearinghouse_state=AsyncMock(
      return_value={
        'balances': [
          {'coin': 'USDC', 'token': 0, 'total': Decimal('120'), 'hold': Decimal(hold)}
        ]
      }
    ),
  )
  shared = Shared(
    client=cast(Hyperliquid, SimpleNamespace(info=info)), maybe_address=ADDRESS
  )
  meta = cast(
    PerpMeta,
    {'asset_idx': 0, 'asset_meta': asset, 'collateral_meta': {'index': 0}},
  )
  return PerpMarket(
    shared=shared, dex={'name': dex, 'idx': 1} if dex else None, meta=meta
  ), info


async def test_leverage_is_shared_per_coin_for_its_ttl():
  """A `ttl` reuses one read per coin; `None` reads the setting again."""
  m, info = market(leverage=[3, 2])
  minute = timedelta(minutes=1)
  assert await m.leverage(ttl=minute) == 3
  assert await m.leverage(ttl=minute) == 3
  assert info.active_asset_data.await_count == 1
  assert await m.leverage() == 2
  assert await m.leverage(ttl=minute) == 2
  assert info.active_asset_data.await_count == 2
  info.active_asset_data.assert_awaited_with(user=ADDRESS, coin='ETC')


async def test_builder_dex_queries_the_prefixed_coin():
  """HIP-3 coins are addressed with their `dex:` prefix, as the universe names them."""
  m, info = market(leverage=[4], dex='xyz')
  assert await m.leverage() == 4
  info.active_asset_data.assert_awaited_with(user=ADDRESS, coin='xyz:ETC')
  info.perp_meta_and_asset_ctxs.assert_awaited_with(dex='xyz')


async def test_available_notional_is_free_unified_balance_times_leverage():
  """`(total - hold) * leverage`, read from the account pool whatever the mode."""
  m, _ = market(leverage=[5])
  assert await m.available_notional() == Decimal(500)


def settable(
  setting: dict[str, Any], asset: dict[str, Any] | None = None
) -> tuple[PerpMarket, SimpleNamespace]:
  """A perpetual whose stub client answers one `activeAssetData` and `updateLeverage`."""
  m, info = market(leverage=[])
  info.active_asset_data = AsyncMock(return_value=asset_data(setting))
  if asset is not None:
    m.meta['asset_meta'].update(asset)  # type: ignore[typeddict-item]
  exchange = SimpleNamespace(
    update_leverage=AsyncMock(return_value={'type': 'default'})
  )
  cast(Any, m.shared.client).exchange = exchange
  return m, exchange


async def test_set_leverage_keeps_cross_and_rereads():
  """A cross setting is updated as cross, and the next read asks afresh."""
  m, exchange = settable({'type': 'cross', 'value': 3})
  minute = timedelta(minutes=1)
  await m.leverage(ttl=minute)
  await m.set_leverage(Decimal(2))
  exchange.update_leverage.assert_awaited_once_with(asset=0, is_cross=True, leverage=2)
  await m.leverage(ttl=minute)
  assert m.shared.client.info.active_asset_data.await_count == 3


async def test_set_leverage_keeps_an_isolated_setting():
  """An isolated setting stays isolated: Hyperliquid refuses a mode switch with a
  position open, and the SDK never changes a margin mode."""
  m, exchange = settable({'type': 'isolated', 'value': 3, 'rawUsd': Decimal(10)})
  await m.set_leverage(Decimal(4))
  exchange.update_leverage.assert_awaited_once_with(asset=0, is_cross=False, leverage=4)


@pytest.mark.parametrize('asset', [{'onlyIsolated': True}, {'marginMode': 'noCross'}])
async def test_set_leverage_is_isolated_where_cross_is_not_allowed(
  asset: dict[str, Any],
):
  """An isolated-only asset (some HIP-3 markets) is set isolated."""
  m, exchange = settable({'type': 'cross', 'value': 3}, asset)
  await m.set_leverage(Decimal(3))
  exchange.update_leverage.assert_awaited_once_with(asset=0, is_cross=False, leverage=3)


@pytest.mark.parametrize('leverage', [Decimal(0), Decimal('1.5')])
async def test_set_leverage_refuses_a_non_whole_multiple(leverage: Decimal):
  """Nothing is sent for a leverage the venue cannot take."""
  m, exchange = settable({'type': 'cross', 'value': 3})
  with pytest.raises(ValueError, match='positive whole number'):
    await m.set_leverage(leverage)
  exchange.update_leverage.assert_not_awaited()
