"""Regression tests for defects found mapping the Binance Earn catalogue."""

from datetime import datetime, timezone
from decimal import Decimal

from typed_binance.spot.http.simple_earn.flexible.list import FlexibleProduct
from typed_binance.spot.http.simple_earn.locked.list import (
  LockedProduct,
  LockedProductDetail,
)

from tribulnation.binance.earn.instruments import parse_flexible, parse_locked

TIME = datetime(2026, 9, 1, tzinfo=timezone.utc)


def flexible_product() -> FlexibleProduct:
  """Build a tiered flexible product; `tierAnnualPercentageRate` is per bracket."""
  return {
    'asset': 'USDT',
    'latestAnnualPercentageRate': Decimal('0.05'),
    'tierAnnualPercentageRate': {'0-500USDT': Decimal('0.03')},
    'canPurchase': True,
    'canRedeem': True,
    'isSoldOut': False,
    'hot': False,
    'minPurchaseAmount': Decimal('0.1'),
    'productId': 'USDT001',
    'subscriptionStartTime': TIME,
    'status': 'PURCHASING',
  }


def boost_only_product() -> LockedProduct:
  """Build a promotional locked listing: an extra reward on top of no base rate.

  8 of the 123 locked products in the live unfiltered listing look like this -- both
  `detail.apr` and `detail.rewardAsset` are absent, and only the `extraReward*` pair
  is present.
  """
  detail: LockedProductDetail = {
    'asset': 'BNB',
    'duration': 90,
    'renewable': True,
    'isSoldOut': False,
    'status': 'PURCHASING',
    'subscriptionStartTime': TIME,
    'extraRewardAsset': 'BNB',
    'extraRewardAPR': Decimal('0.01'),
  }
  return {
    'projectId': 'Bnb*90',
    'detail': detail,
    'quota': {
      'totalPersonalQuota': Decimal('1000000'),
      'minimum': Decimal('0.05'),
    },
  }


def test_a_tier_rate_is_not_added_to_the_base_rate():
  """`tierAnnualPercentageRate` is the rate for a balance bracket, not a bonus on top.

  Summing the two reported 8% for a 5% product and minted one extra `Instrument` per
  bracket.
  """
  instrument = parse_flexible(flexible_product())
  assert instrument is not None
  assert instrument.apr == Decimal('0.05')


def test_a_boost_only_locked_listing_is_skipped_not_crashed_on():
  """No base rate and no reward asset used to raise `KeyError` from `set().pop()`.

  The whole `locked_instruments()` sweep died on it, since the unfiltered listing
  really does carry these rows.
  """
  assert parse_locked(boost_only_product()) is None
