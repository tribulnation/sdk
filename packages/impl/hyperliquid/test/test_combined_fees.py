"""Hyperliquid's official fee formula for default, HIP-3 and spot markets."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast
from typed_hyperliquid import Hyperliquid

from tribulnation.hyperliquid.market.impl.fees import (
  PerpArgs,
  SpotArgs,
  fee_rates,
  personal_perp_fees,
  personal_spot_fees,
  standard_perp_fees,
  standard_spot_fees,
)
from tribulnation.hyperliquid.market.impl.mixin import (
  PerpMarketMixin,
  Shared,
  SpotMarketMixin,
)

D = Decimal
USER_FEES = {
  'userAddRate': D('0.00015'),
  'userCrossRate': D('0.00045'),
  'userSpotAddRate': D('0.0004'),
  'userSpotCrossRate': D('0.0007'),
  'activeReferralDiscount': D('0.04'),
}
SCHEDULE = {
  'add': D('0.00015'),
  'cross': D('0.00045'),
  'spotAdd': D('0.0004'),
  'spotCross': D('0.0007'),
}


def perp(scale: str | None, growth: bool) -> PerpArgs:
  """Perpetual inputs; `None` scale is the default dex."""
  return {
    'type': 'perp',
    'deployer_fee_scale': D(scale) if scale is not None else D(0),
    'growth_mode': growth,
  }


def spot(stable: bool) -> SpotArgs:
  """Spot inputs."""
  return {'type': 'spot', 'stable_pair': stable}


@pytest.mark.parametrize(
  'maker, taker, referral, args, expected_maker, expected_taker',
  [
    # Default dex: scaleIfHip3 = 1, referral discounts charges.
    ('0.00015', '0.00045', '0.04', perp(None, False), '0.000144', '0.000432'),
    ('0.00015', '0.00045', '0', perp(None, False), '0.00015', '0.00045'),
    # HIP-3 growth mode, scale 1.0: x2 for HIP-3, x0.1 for growth mode.
    ('0.00015', '0.00045', '0.04', perp('1.0', True), '0.0000288', '0.0000864'),
    ('0.00015', '0.00045', '0', perp('1.0', False), '0.00030', '0.00090'),
    # Scale below 1: x(1 + s).
    (
      '0.00015',
      '0.00045',
      '0.04',
      perp('0.1111', False),
      '0.0001599984',
      '0.0004799952',
    ),
    ('0.00015', '0.00045', '0', perp('0.5', False), '0.000225', '0.000675'),
    # Scale above 1: x2s.
    ('0.00015', '0.00045', '0', perp('1.5', False), '0.00045', '0.00135'),
    # A maker rebate takes growth mode, but neither HIP-3 scaling nor referral.
    ('-0.00001', '0.00045', '0.04', perp('1.0', True), '-0.000001', '0.0000864'),
    ('-0.00001', '0.00045', '0.04', perp(None, False), '-0.00001', '0.000432'),
    ('0', '0.00045', '0.04', perp('1.0', True), '0', '0.0000864'),
    # Spot: no HIP-3 or growth scaling; stable pairs x0.2.
    ('0.0004', '0.0007', '0.04', spot(False), '0.000384', '0.000672'),
    ('0.0004', '0.0007', '0.04', spot(True), '0.0000768', '0.0001344'),
    ('-0.00001', '0.0007', '0', spot(True), '-0.000002', '0.00014'),
  ],
)
def test_fee_rates_vectors(
  maker: str,
  taker: str,
  referral: str,
  args: PerpArgs | SpotArgs,
  expected_maker: str,
  expected_taker: str,
):
  """Every branch of the official formula, without the aligned quote branches."""
  fees = fee_rates(
    maker_rate=D(maker), taker_rate=D(taker), referral=D(referral), args=args
  )
  assert fees.maker_buy == fees.maker_sell == D(expected_maker)
  assert fees.taker_buy == fees.taker_sell == D(expected_taker)


@pytest.mark.parametrize(
  'referral, rate, scale',
  [
    ('1.5', '0.0001', '1'),
    ('NaN', '0.0001', '1'),
    ('0', 'Infinity', '1'),
    ('0', '0', '-1'),
  ],
)
def test_fee_rates_reject_malformed_inputs(referral: str, rate: str, scale: str):
  """Malformed rates, referral fractions or scales are failures, not fees."""
  with pytest.raises(ValueError):
    fee_rates(
      maker_rate=D(rate),
      taker_rate=D('0.0001'),
      referral=D(referral),
      args=perp(scale, False),
    )


def shared() -> SimpleNamespace:
  """Fee loaders and a USDC/USDE/USDH/USDT0 quote set."""
  return SimpleNamespace(
    load_user_fees=AsyncMock(return_value=USER_FEES),
    load_standard_fee_schedule=AsyncMock(return_value=SCHEDULE),
    load_spot_quote_tokens=AsyncMock(return_value=frozenset({0, 235, 268, 360})),
  )


def perp_market(
  *,
  dex: str | None = None,
  collateral: tuple[int, str] = (0, 'USDC'),
  asset: dict[str, Any] | None = None,
) -> PerpMarketMixin:
  """A perpetual market with the given dex, collateral and asset metadata."""
  return cast(
    PerpMarketMixin,
    SimpleNamespace(
      dex={'name': dex, 'idx': 1} if dex else None,
      collateral_meta={'index': collateral[0], 'name': collateral[1]},
      asset_meta={'name': 'X', 'szDecimals': 3, **(asset or {})},
      shared=shared(),
    ),
  )


def spot_market(*, base: tuple[int, str], quote: tuple[int, str]) -> SpotMarketMixin:
  """A spot market between the given base and quote tokens."""
  base_meta: dict[str, object] = {'index': base[0], 'name': base[1], 'szDecimals': 5}
  quote_meta: dict[str, object] = {'index': quote[0], 'name': quote[1]}
  return cast(
    SpotMarketMixin,
    SimpleNamespace(
      base_meta=base_meta,
      quote_meta=quote_meta,
      meta={'base_meta': base_meta, 'quote_meta': quote_meta, 'asset_meta': {}},
      shared=shared(),
    ),
  )


HIP3_GROWTH: dict[str, Any] = {'deployerFeeScale': D('1.0'), 'growthMode': 'enabled'}


async def test_default_perp_fees():
  """The default dex has no deployerFeeScale and scales by 1."""
  target = perp_market()
  fees = await personal_perp_fees(target, refetch=True)
  assert (fees.maker_buy, fees.taker_buy) == (D('0.000144'), D('0.000432'))
  cast(AsyncMock, target.shared.load_user_fees).assert_awaited_once_with(refetch=True)
  standard = await standard_perp_fees(target, refetch=True)
  assert standard is not None
  assert (standard.maker_buy, standard.taker_buy) == (D('0.00015'), D('0.00045'))
  cast(AsyncMock, target.shared.load_user_fees).assert_awaited_once()


async def test_hip3_perp_fees_use_per_asset_metadata():
  """HIP-3 USDC markets apply the asset's scale and growth mode."""
  target = perp_market(dex='xyz', asset=HIP3_GROWTH)
  fees = await personal_perp_fees(target)
  assert (fees.maker_buy, fees.taker_sell) == (D('0.0000288'), D('0.0000864'))
  standard = await standard_perp_fees(target)
  assert standard is not None
  assert (standard.maker_sell, standard.taker_buy) == (D('0.00003'), D('0.00009'))


@pytest.mark.parametrize('collateral', [(360, 'USDH'), (235, 'USDE'), (268, 'USDT0')])
async def test_non_usdc_collateral_is_declined(collateral: tuple[int, str]):
  """Aligned quote status of non-USDC collateral cannot be read, so fees are declined."""
  target = perp_market(dex='flx', collateral=collateral, asset=HIP3_GROWTH)
  assert await standard_perp_fees(target) is None
  with pytest.raises(NotImplementedError, match=collateral[1]):
    await personal_perp_fees(target)
  cast(AsyncMock, target.shared.load_user_fees).assert_not_awaited()


async def test_hip3_asset_without_scale_is_declined():
  """A missing HIP-3 scale is not a zero adjustment."""
  target = perp_market(dex='xyz')
  assert await standard_perp_fees(target) is None
  with pytest.raises(NotImplementedError, match='deployerFeeScale'):
    await personal_perp_fees(target)


@pytest.mark.parametrize(
  'base, quote, maker, taker',
  [
    ((142, 'UBTC'), (0, 'USDC'), '0.000384', '0.000672'),
    ((150, 'HYPE'), (235, 'USDE'), '0.000384', '0.000672'),
    ((268, 'USDT0'), (0, 'USDC'), '0.0000768', '0.0001344'),
    ((235, 'USDE'), (0, 'USDC'), '0.0000768', '0.0001344'),
  ],
)
async def test_spot_fees(
  base: tuple[int, str], quote: tuple[int, str], maker: str, taker: str
):
  """USDC and USDE quotes use the spot rates; two quote tokens make a stable pair."""
  target = spot_market(base=base, quote=quote)
  fees = await personal_spot_fees(target, refetch=True)
  assert (fees.maker_buy, fees.taker_sell) == (D(maker), D(taker))
  cast(AsyncMock, target.shared.load_user_fees).assert_awaited_once_with(refetch=True)
  standard = await standard_spot_fees(target)
  assert standard is not None
  assert standard.maker_buy == D(maker) / D('0.96')
  assert standard.taker_buy == D(taker) / D('0.96')


@pytest.mark.parametrize('quote', [(360, 'USDH'), (268, 'USDT0')])
async def test_other_spot_quotes_are_declined(quote: tuple[int, str]):
  """Quotes without verified alignment status return no fees."""
  target = spot_market(base=(150, 'HYPE'), quote=quote)
  assert await standard_spot_fees(target) is None
  with pytest.raises(NotImplementedError, match=quote[1]):
    await personal_spot_fees(target)
  cast(AsyncMock, target.shared.load_user_fees).assert_not_awaited()


async def test_spot_quote_tokens_are_cached_with_metadata():
  """The quote set is derived from spotMeta's universe and refreshed with it."""
  spot_meta: dict[str, Any] = {
    'tokens': [],
    'universe': [
      {'index': 0, 'tokens': [150, 0]},
      {'index': 1, 'tokens': [268, 0]},
      {'index': 2, 'tokens': [150, 235]},
    ],
  }
  request = AsyncMock(return_value=spot_meta)
  target = Shared(
    client=cast(Hyperliquid, SimpleNamespace(info=SimpleNamespace(spot_meta=request)))
  )
  assert await target.load_spot_quote_tokens() == frozenset({0, 235})
  assert await target.load_spot_quote_tokens() == frozenset({0, 235})
  request.assert_awaited_once()
  await target.load_spot_quote_tokens(refetch=True)
  assert request.await_count == 2


async def test_public_schedule_uses_fixed_zero_address_and_caches():
  """Configured account identity cannot leak into public baseline discovery."""
  request = AsyncMock(return_value={'feeSchedule': SCHEDULE})
  target = Shared(
    client=cast(Hyperliquid, SimpleNamespace(info=SimpleNamespace(user_fees=request))),
    maybe_address='private-account',
  )
  assert (
    await target.load_standard_fee_schedule()
    == await target.load_standard_fee_schedule()
  )
  request.assert_awaited_once_with(user='0x' + '0' * 40)
  await target.load_standard_fee_schedule(refetch=True)
  assert request.await_count == 2
