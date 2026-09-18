"""Earn products with reused native IDs remain separate, unidentified instruments."""

from datetime import timedelta
from decimal import Decimal

from typed_bybit.finance.easy_onchain.product_info import EarnProduct
from typed_bybit.finance.fixed_saving.product import FixedSavingProduct

from tribulnation.bybit.earn.instruments import parse_easy_onchain, parse_fixed_saving


FIXED: FixedSavingProduct = {
  'productId': '4',
  'category': 'FixedTermSaving',
  'coin': 'USDT',
  'duration': '7d',
  'status': 'Available',
  'tieredApyList': [{'min': '1', 'max': '100', 'apy': '3%'}],
  'minStakeAmount': Decimal('1'),
  'maxStakeAmount': Decimal('100'),
  'precision': 6,
}

FLEXIBLE: EarnProduct = {
  'productId': '4',
  'category': 'FlexibleSaving',
  'coin': 'ETH',
  'estimateApr': '2%',
  'minStakeAmount': Decimal('0.01'),
  'maxStakeAmount': Decimal('10'),
  'precision': '8',
  'status': 'Available',
  'duration': 'Flexible',
}


def test_shared_native_id_across_families_is_not_an_sdk_identity():
  """Savings and staking may share a native ID without sharing SDK identity."""
  instruments = [
    parse_fixed_saving(FIXED),
    parse_easy_onchain('FlexibleSaving', FLEXIBLE),
    parse_easy_onchain('OnChain', {**FLEXIBLE, 'category': 'OnChain', 'coin': 'SOL'}),
  ]
  assert all(instrument.id is None for instrument in instruments)
  assert [(i.asset, i.tags, i.apr, i.duration) for i in instruments] == [
    ('USDT', ['fixed'], Decimal('0.03'), timedelta(days=7)),
    ('ETH', ['flexible'], Decimal('0.02'), None),
    ('SOL', ['staking'], Decimal('0.02'), None),
  ]


def test_shared_native_id_preserves_fixed_terms_and_quantity_bounds():
  """Same-family collisions do not discard term or quantity information."""
  instruments = [
    parse_fixed_saving(FIXED),
    parse_fixed_saving({**FIXED, 'duration': '90d'}),
    parse_fixed_saving(
      {**FIXED, 'minStakeAmount': Decimal('100'), 'maxStakeAmount': Decimal('1000')}
    ),
  ]
  assert all(instrument.id is None for instrument in instruments)
  assert [(i.duration, i.min_qty, i.max_qty) for i in instruments] == [
    (timedelta(days=7), Decimal('1'), Decimal('100')),
    (timedelta(days=90), Decimal('1'), Decimal('100')),
    (timedelta(days=7), Decimal('100'), Decimal('1000')),
  ]
