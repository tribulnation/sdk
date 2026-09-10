"""Public Hyperliquid specifications do not read a user's account fee tier."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from typing_extensions import cast

from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin, SpotMarketMixin
from tribulnation.hyperliquid.market.impl.perps_rules import rules as perp_rules
from tribulnation.hyperliquid.market.impl.spot_rules import rules as spot_rules


async def test_spot_rules_do_not_fetch_user_fees():
  """Numeric asset translations and market precision need no account address."""
  personal = AsyncMock(side_effect=AssertionError('Private fee query called'))
  target = cast(
    SpotMarketMixin,
    SimpleNamespace(
      shared=SimpleNamespace(load_user_fees=personal),
      meta={
        'base_meta': {'index': 197, 'szDecimals': 5},
        'quote_meta': {'index': 0},
        'asset_meta': {},
      },
    ),
  )
  rules = await spot_rules(target)
  assert rules.fee_asset == '0'
  assert rules.fees is None
  assert 'user_fees' not in rules.details
  personal.assert_not_awaited()


async def test_perp_rules_do_not_fetch_user_fees():
  """HIP-3 metadata remains usable without guessing deployer-adjusted fees."""
  personal = AsyncMock(side_effect=AssertionError('Private fee query called'))
  target = cast(
    PerpMarketMixin,
    SimpleNamespace(
      shared=SimpleNamespace(load_user_fees=personal),
      asset_meta={'szDecimals': 3},
      asset_name='xyz:XYZ',
      dex={'name': 'xyz', 'idx': 1},
      collateral_name='USDC',
      collateral_meta={'index': 0},
    ),
  )
  rules = await perp_rules(target)
  assert rules.fee_asset == 'USDC'
  assert rules.fees is None
  assert 'user_fees' not in rules.details
  personal.assert_not_awaited()
