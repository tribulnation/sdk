"""Unit tests for the Kraken earn parsers, over `Earn/Strategies` rows recorded from the
live venue on 2026-09-08."""

from datetime import timedelta
from decimal import Decimal

from tribulnation.kraken.earn.instruments import parse_apr, parse_instrument, parse_tags

from typed_kraken.spot.earn.strategies import EarnStrategy

NAMES = {'BTC': 'XXBT', 'ETH': 'XETH', 'SOL': 'SOL'}

BONDED: EarnStrategy = {
  'id': 'ESZ4QWD-E7FCW-7PBERA',
  'asset': 'BTC',
  'lock_type': {'type': 'bonded', 'bonding_period': 0, 'unbonding_period': 2592000},
  'apr_estimate': {'low': Decimal('0.1500'), 'high': Decimal('0.1500')},
  'user_min_allocation': Decimal('0.0000'),
  'user_cap': None,
  'can_allocate': True,
  'yield_source': {'type': 'opt_in_rewards'},
}

FLEX: EarnStrategy = {
  'id': 'ESH27TO-MZXF4-ZYLVTX',
  'asset': 'BTC',
  'lock_type': {'type': 'flex'},
  'apr_estimate': {'low': Decimal('0.1000'), 'high': Decimal('0.1000')},
  'user_min_allocation': None,
  'user_cap': Decimal('50.0000000000'),
  'can_allocate': False,
  'yield_source': {'type': 'opt_in_rewards'},
}


def test_asset_is_emitted_as_the_internal_id():
  """Strategies name assets by display name; every other surface uses the internal
  id, so that is what comes out."""
  instrument = parse_instrument(BONDED, NAMES)
  assert instrument is not None and instrument.asset == 'XXBT'
  unknown = parse_instrument({**BONDED, 'asset': 'NEW'}, NAMES)
  assert unknown is not None and unknown.asset == 'NEW'


def test_apr_is_the_midpoint_of_the_percent_range():
  """`low`/`high` are percentage points; a differing pair collapses to its midpoint."""
  assert parse_apr(BONDED) == Decimal('0.0015')
  spread: EarnStrategy = {
    **BONDED,
    'apr_estimate': {'low': Decimal('2.0000'), 'high': Decimal('4.0000')},
  }
  assert parse_apr(spread) == Decimal('0.03')
  assert parse_apr({**BONDED, 'apr_estimate': None}) is None
  assert parse_instrument({**BONDED, 'apr_estimate': None}, NAMES) is None


def test_min_qty_stays_unset_and_max_qty_is_the_native_cap():
  """`user_min_allocation` is in USD, not the asset, so it cannot fill `min_qty`."""
  bonded = parse_instrument(BONDED, NAMES)
  flex = parse_instrument(FLEX, NAMES)
  assert bonded is not None and flex is not None
  assert bonded.min_qty is None and bonded.max_qty is None
  assert flex.min_qty is None and flex.max_qty == Decimal('50.0000000000')


def test_tags_and_duration_follow_the_lock_type():
  """`instant` and `flex` are unbonded; `bonded` is fixed for bonding plus unbonding."""
  assert parse_tags(FLEX) == ['flexible']
  assert parse_tags(BONDED) == ['fixed']
  staking: EarnStrategy = {
    **FLEX,
    'lock_type': {'type': 'instant', 'payout_frequency': 604800},
    'yield_source': {'type': 'staking'},
  }
  assert parse_tags(staking) == ['flexible', 'staking']
  bonded = parse_instrument(BONDED, NAMES)
  flex = parse_instrument(FLEX, NAMES)
  assert bonded is not None and bonded.duration == timedelta(days=30)
  assert flex is not None and flex.duration is None
