"""Native fees combine account adjustments without guessing unresolved market rates."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import cast
from typed_hyperliquid import Hyperliquid

from tribulnation.hyperliquid.market.impl.fees import (
  personal_perp_fees,
  standard_perp_fees,
)
from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin, Shared
from tribulnation.hyperliquid.market.spot_market import SpotMarket


def market(
  *, maker: str = '0.00015', dex: str | None = None, collateral: int = 0
) -> PerpMarketMixin:
  """Supply complete native fee components with an already staking-adjusted tier."""
  return cast(
    PerpMarketMixin,
    SimpleNamespace(
      dex={'name': dex, 'idx': 1} if dex else None,
      collateral_meta={'index': collateral},
      asset_meta={'szDecimals': 3},
      shared=SimpleNamespace(
        load_user_fees=AsyncMock(
          return_value={
            'userAddRate': Decimal(maker),
            'userCrossRate': Decimal('0.00045'),
            'activeReferralDiscount': Decimal('0.04'),
            'activeStakingDiscount': {'discount': Decimal('0.4')},
          }
        ),
        load_standard_fee_schedule=AsyncMock(
          return_value={
            'add': Decimal('0.00015'),
            'cross': Decimal('0.00045'),
          }
        ),
      ),
    ),
  )


async def test_native_public_rates_are_independent_of_personal_tier():
  """The baseline uses feeSchedule and no configured account lookup."""
  target = market()
  fees = await standard_perp_fees(target, refetch=True)
  assert fees is not None
  assert fees.maker_buy == fees.maker_sell == Decimal('0.00015')
  assert fees.taker_buy == fees.taker_sell == Decimal('0.00045')
  cast(AsyncMock, target.shared.load_user_fees).assert_not_awaited()
  cast(AsyncMock, target.shared.load_standard_fee_schedule).assert_awaited_once_with(
    refetch=True
  )


@pytest.mark.parametrize(
  'maker, expected', [('0.00015', '0.000144'), ('-0.00001', '-0.00001'), ('0', '0')]
)
async def test_referral_adjusts_charges_not_rebates_or_staking_twice(
  maker: str, expected: str
):
  """Official user rates include staking, but active referral remains separate."""
  target = market(maker=maker)
  fees = await personal_perp_fees(target, refetch=True)
  assert fees.maker_buy == fees.maker_sell == Decimal(expected)
  assert fees.taker_buy == fees.taker_sell == Decimal('0.000432')
  cast(AsyncMock, target.shared.load_user_fees).assert_awaited_once_with(refetch=True)


@pytest.mark.parametrize('dex, collateral', [('xyz', 0), ('flx', 360), (None, 360)])
async def test_unresolved_perp_metadata_does_not_return_global_rates(
  dex: str | None, collateral: int
):
  """Missing per-asset fee scale/aligned quote state is not a zero adjustment."""
  target = market(dex=dex, collateral=collateral)
  assert await standard_perp_fees(target) is None
  with pytest.raises(NotImplementedError, match='metadata'):
    await personal_perp_fees(target)
  cast(AsyncMock, target.shared.load_user_fees).assert_not_awaited()


async def test_spot_does_not_guess_stable_pair_and_aligned_quote_adjustments():
  """The documented alignedQuoteTokenInfo request currently fails on mainnet."""
  with pytest.raises(NotImplementedError, match='quote-token'):
    await SpotMarket.fees(cast(SpotMarket, SimpleNamespace()))


async def test_public_schedule_uses_fixed_zero_address_and_caches():
  """Configured account identity cannot leak into public baseline discovery."""
  request = AsyncMock(
    return_value={
      'feeSchedule': {'add': Decimal('0.00015'), 'cross': Decimal('0.00045')}
    }
  )
  shared = Shared(
    client=cast(Hyperliquid, SimpleNamespace(info=SimpleNamespace(user_fees=request))),
    maybe_address='private-account',
  )
  assert (
    await shared.load_standard_fee_schedule()
    == await shared.load_standard_fee_schedule()
  )
  request.assert_awaited_once_with(user='0x' + '0' * 40)
  await shared.load_standard_fee_schedule(refetch=True)
  assert request.await_count == 2
