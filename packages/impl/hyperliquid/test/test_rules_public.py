"""Public Hyperliquid specifications do not read a user's account fee tier."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from typing_extensions import cast

from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin, SpotMarketMixin
from tribulnation.hyperliquid.market.impl.perps_rules import rules as perp_rules
from tribulnation.hyperliquid.market.impl.spot_rules import rules as spot_rules

SCHEDULE = {
  'add': Decimal('0.00015'),
  'cross': Decimal('0.00045'),
  'spotAdd': Decimal('0.0004'),
  'spotCross': Decimal('0.0007'),
}


def shared() -> SimpleNamespace:
  """Loaders where any personal fee query fails the test."""
  return SimpleNamespace(
    load_user_fees=AsyncMock(side_effect=AssertionError('Private fee query called')),
    load_standard_fee_schedule=AsyncMock(return_value=SCHEDULE),
    load_spot_quote_tokens=AsyncMock(return_value=frozenset({0, 235, 268, 360})),
  )


def spot_market(quote: dict[str, object]) -> SpotMarketMixin:
  """A UBTC spot market quoted in `quote`."""
  base: dict[str, object] = {'index': 197, 'name': 'UBTC', 'szDecimals': 5}
  return cast(
    SpotMarketMixin,
    SimpleNamespace(
      shared=shared(),
      base_meta=base,
      quote_meta=quote,
      meta={'base_meta': base, 'quote_meta': quote, 'asset_meta': {}},
    ),
  )


async def test_spot_rules_do_not_fetch_user_fees():
  """USDC-quoted spot uses the standard spot schedule; the fee asset depends on the fill."""
  target = spot_market({'index': 0, 'name': 'USDC'})
  rules = await spot_rules(target)
  assert rules.fee_asset is None
  assert rules.fees is not None
  assert rules.fees.maker_buy == Decimal('0.0004')
  assert rules.fees.taker_sell == Decimal('0.0007')
  assert 'user_fees' not in rules.details
  cast(AsyncMock, target.shared.load_user_fees).assert_not_awaited()


async def test_spot_rules_decline_unverified_quotes():
  """USDH-quoted spot keeps its specifications without a fee schedule."""
  target = spot_market({'index': 360, 'name': 'USDH'})
  rules = await spot_rules(target)
  assert rules.fee_asset is None
  assert rules.fees is None


def perp_market(collateral: dict[str, object]) -> PerpMarketMixin:
  """A HIP-3 growth-mode perpetual with the given collateral."""
  return cast(
    PerpMarketMixin,
    SimpleNamespace(
      shared=shared(),
      asset_meta={
        'name': 'xyz:XYZ',
        'szDecimals': 3,
        'deployerFeeScale': Decimal('1.0'),
        'growthMode': 'enabled',
      },
      asset_name='xyz:XYZ',
      dex={'name': 'xyz', 'idx': 1},
      collateral_meta=collateral,
    ),
  )


async def test_perp_rules_do_not_fetch_user_fees():
  """HIP-3 USDC rules apply the asset's scale and name the collateral by index."""
  target = perp_market({'index': 0, 'name': 'USDC'})
  rules = await perp_rules(target)
  assert rules.fee_asset == '0'
  assert rules.fees is not None
  assert rules.fees.maker_buy == Decimal('0.00003')
  assert rules.fees.taker_buy == Decimal('0.00009')
  assert 'user_fees' not in rules.details
  cast(AsyncMock, target.shared.load_user_fees).assert_not_awaited()


async def test_perp_rules_decline_unverified_collateral():
  """USDH-collateral rules name the collateral index but return no schedule."""
  rules = await perp_rules(perp_market({'index': 360, 'name': 'USDH'}))
  assert rules.fee_asset == '360'
  assert rules.fees is None
