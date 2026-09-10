"""Public fee tiers must not depend on a configured dYdX account."""

from decimal import Decimal
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import cast

from typed_dydx import Dydx
from typed_dydx.indexer.schemas import PerpetualMarket
from typed_dydx.protos.dydxprotocol import feetiers as proto
from tribulnation.dydx.market.impl.mixin import Shared
from tribulnation.dydx.market.impl.fees import combined_fees, market_charge
from tribulnation.sdk.core import NetworkError
from typed_core.exceptions import NetworkError as TypedNetworkError


def shared(tiers: list[proto.PerpetualFeeTier]) -> tuple[Shared, AsyncMock, AsyncMock]:
  """Build a public client whose private fee path fails if accidentally used."""
  public = AsyncMock(return_value=SimpleNamespace(params=SimpleNamespace(tiers=tiers)))
  private = AsyncMock(side_effect=AssertionError('Private fee query called'))
  client = cast(
    Dydx,
    SimpleNamespace(
      chain=SimpleNamespace(
        feetiers=SimpleNamespace(
          perpetual_fee_params=public,
          user_fee_tier=private,
        )
      )
    ),
  )
  return Shared(client=client, address=None), public, private


async def test_base_tier_is_selected_by_requirements_not_order():
  """VIP tiers may precede the standard tier; genuine zero fees remain zero."""
  base = proto.PerpetualFeeTier(maker_fee_ppm=0, taker_fee_ppm=500)
  vip = proto.PerpetualFeeTier(absolute_volume_requirement=10000, taker_fee_ppm=100)
  target, public, private = shared([vip, base])
  assert await target.load_standard_fee_tier() is base
  assert await target.load_standard_fee_tier() is base
  public.assert_awaited_once_with()
  await target.load_standard_fee_tier(refetch=True)
  assert public.await_count == 2
  private.assert_not_awaited()


async def test_market_discount_lookup_uses_exact_clob_pair_and_chain_clock(
  monkeypatch: pytest.MonkeyPatch,
):
  """A campaign on another market cannot alter this market's fee schedule."""
  target, _, _ = shared([])
  now = datetime(2026, 9, 10, tzinfo=timezone.utc)
  campaign = proto.PerMarketFeeDiscountParams(
    clob_pair_id=123,
    start_time=now,
    end_time=now + timedelta(minutes=1),
    charge_ppm=0,
  )
  query = AsyncMock(return_value=[campaign])
  monkeypatch.setattr(
    'tribulnation.dydx.market.impl.mixin.market_discount_params', query
  )
  block = AsyncMock(
    return_value=SimpleNamespace(
      block=SimpleNamespace(header=SimpleNamespace(time=now))
    )
  )
  monkeypatch.setattr(
    target.client.chain,
    'tendermint',
    SimpleNamespace(get_latest_block=block),
    raising=False,
  )
  assert await target.load_market_charge(0) == 1000000
  block.assert_not_awaited()
  assert await target.load_market_charge(123) == 0
  block.assert_awaited_once_with()
  assert query.await_count == 1
  await target.load_market_charge(0, refetch=True)
  assert query.await_count == 2


async def test_market_discount_request_failure_is_not_no_discount(
  monkeypatch: pytest.MonkeyPatch,
):
  """A failed required query blocks the fee result and preserves SDK errors."""
  target, _, _ = shared([])
  monkeypatch.setattr(
    'tribulnation.dydx.market.impl.mixin.market_discount_params',
    AsyncMock(side_effect=TypedNetworkError('Unavailable')),
  )
  with pytest.raises(NetworkError):
    await target.load_market_charge(0)
  assert target.market_discounts is None


@pytest.mark.parametrize(
  'tiers', [[], [proto.PerpetualFeeTier(), proto.PerpetualFeeTier()]]
)
async def test_missing_or_ambiguous_base_tier_fails(
  tiers: list[proto.PerpetualFeeTier],
):
  """Never choose a private/promotional tier or fabricate a rate on malformed data."""
  target, _, private = shared(tiers)
  with pytest.raises(ValueError, match='one base tier'):
    await target.load_standard_fee_tier()
  private.assert_not_awaited()


async def test_rules_use_public_standard_tier(monkeypatch: pytest.MonkeyPatch):
  """Market metadata remains available with no address or private fee endpoint."""
  target, _, private = shared(
    [proto.PerpetualFeeTier(maker_fee_ppm=100, taker_fee_ppm=500)]
  )
  monkeypatch.setattr(
    Shared,
    'load_markets',
    AsyncMock(
      return_value={
        'BTC-USD': {
          'ticker': 'BTC-USD',
          'tickSize': '0.1',
          'stepSize': '0.001',
          'status': 'ACTIVE',
          'clobPairId': '0',
        }
      }
    ),
  )
  monkeypatch.setattr(Shared, 'load_market_charge', AsyncMock(return_value=500000))
  rules = await target.rules('BTC-USD')
  assert rules.fees is not None
  assert rules.fees.maker_buy == rules.fees.maker_sell == Decimal('0.00005')
  assert rules.fees.taker_buy == rules.fees.taker_sell == Decimal('0.00025')
  assert not hasattr(rules, 'base') and not hasattr(rules, 'quote')
  assert rules.fee_asset == 'USDC'
  assert 'user_fees' not in rules.details
  private.assert_not_awaited()


@pytest.mark.parametrize(
  'offset, expected', [(-1, 1000000), (0, 500000), (59, 500000), (60, 1000000)]
)
def test_market_holiday_window(offset: int, expected: int):
  """The fee campaign begins inclusively and ends exclusively on chain time."""
  start = datetime(2026, 9, 10, tzinfo=timezone.utc)
  discount = proto.PerMarketFeeDiscountParams(
    clob_pair_id=0,
    start_time=start,
    end_time=start + timedelta(minutes=1),
    charge_ppm=500000,
  )
  assert market_charge(discount, start + timedelta(seconds=offset)) == expected


def test_fee_discounts_match_signed_integer_rounding_and_order():
  """Rebates round toward zero; staking affects positive post-holiday fees only."""
  tier = proto.PerpetualFeeTier(maker_fee_ppm=-11, taker_fee_ppm=11)
  fees = combined_fees(tier, charge_ppm=500000, staking_discount_ppm=500000)
  assert fees.maker_buy == fees.maker_sell == Decimal('-0.000005')
  assert fees.taker_buy == fees.taker_sell == Decimal('0.000002')


def test_fee_free_holiday_removes_charges_and_rebates():
  """A true zero market multiplier affects both signs of fees."""
  tier = proto.PerpetualFeeTier(maker_fee_ppm=-100, taker_fee_ppm=500)
  fees = combined_fees(tier, charge_ppm=0, staking_discount_ppm=0)
  assert fees.maker_buy == fees.taker_sell == Decimal(0)


@pytest.mark.parametrize(
  'charge, staking', [(-1, 0), (1000001, 0), (1000000, -1), (1000000, 1000001)]
)
def test_invalid_fee_multipliers_fail(charge: int, staking: int):
  """Malformed metadata cannot masquerade as a complete account schedule."""
  with pytest.raises(ValueError, match='multipliers'):
    combined_fees(
      proto.PerpetualFeeTier(), charge_ppm=charge, staking_discount_ppm=staking
    )


async def test_personal_tier_applies_staking_without_changing_rebates(
  monkeypatch: pytest.MonkeyPatch,
):
  """The account tier (including upstream referral override) is adjusted exactly once."""
  tier = proto.PerpetualFeeTier(name='VIP', maker_fee_ppm=-11, taker_fee_ppm=11)
  target, _, private = shared([])
  target.address = 'dydx1test'
  target.fee_tier = tier
  staking = AsyncMock(
    return_value=proto.QueryUserStakingTierResponse(
      fee_tier_name='VIP', discount_ppm=500000
    )
  )
  monkeypatch.setattr(
    target.client.chain.feetiers, 'user_staking_tier', staking, raising=False
  )
  monkeypatch.setattr(Shared, 'load_market_charge', AsyncMock(return_value=500000))
  fees = await target.fees(cast(PerpetualMarket, {'clobPairId': '0'}), personal=True)
  assert fees.maker_buy == Decimal('-0.000005')
  assert fees.taker_sell == Decimal('0.000002')
  staking.assert_awaited_once_with('dydx1test')
  private.assert_not_awaited()
