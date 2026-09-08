"""Tests for Hyperliquid collateral calculations."""

from datetime import datetime, timezone
from decimal import Decimal

from typed_hyperliquid.info.clearinghouse_state import (
  ClearinghouseState,
  IsolatedLeverage,
  PerpPosition,
)

from tribulnation.hyperliquid.market.impl.collateral import (
  cross_collateral,
  isolated_collateral,
)

TIME = datetime(2026, 3, 20, tzinfo=timezone.utc)
"""Snapshot time; the collateral maths never reads it."""

LEVERAGE: IsolatedLeverage = {'type': 'isolated', 'value': 10, 'rawUsd': Decimal('500')}


def cross_state() -> ClearinghouseState:
  """An account state with no open positions, as the client hands it over."""
  return {
    'assetPositions': [],
    'crossMaintenanceMarginUsed': Decimal('100'),
    'crossMarginSummary': {
      'accountValue': Decimal('1000'),
      'totalMarginUsed': Decimal('200'),
      'totalNtlPos': Decimal('3000'),
      'totalRawUsd': Decimal('1000'),
    },
    'marginSummary': {
      'accountValue': Decimal('1000'),
      'totalMarginUsed': Decimal('200'),
      'totalNtlPos': Decimal('3000'),
      'totalRawUsd': Decimal('1000'),
    },
    'time': TIME,
    'withdrawable': Decimal('800'),
  }


def isolated_position(
  *, liquidation_px: Decimal | None = Decimal('45000')
) -> PerpPosition:
  """One isolated BTC position, margined by `LEVERAGE`."""
  return {
    'coin': 'BTC',
    'cumFunding': {
      'allTime': Decimal(0),
      'sinceChange': Decimal(0),
      'sinceOpen': Decimal(0),
    },
    'entryPx': Decimal('50000'),
    'leverage': LEVERAGE,
    'liquidationPx': liquidation_px,
    'marginUsed': Decimal('500'),
    'maxLeverage': 50,
    'positionValue': Decimal('5000'),
    'returnOnEquity': Decimal(0),
    'szi': Decimal('0.1'),
    'unrealizedPnl': Decimal('120'),
  }


def test_cross_collateral_math() -> None:
  """Cross bucket reads straight from the venue summary; every field non-None."""
  c = cross_collateral(
    cross_state(), spot_equity=Decimal('1000'), free_collateral=Decimal('800')
  )
  assert c.equity == Decimal('1000')
  assert c.free_collateral == Decimal('800')
  assert c.initial_margin == Decimal('200')
  assert c.maintenance_margin == Decimal('100')
  assert c.leverage == Decimal('3')  # totalNtlPos / spot_equity
  assert c.margin_mode == 'cross'
  assert c.maintenance_ratio == Decimal('0.1')


def test_cross_collateral_non_positive_equity() -> None:
  """Zero equity => 0 leverage and +Infinity maintenance_ratio (no div-by-zero)."""
  state = cross_state()
  state['crossMarginSummary'] = {
    'accountValue': Decimal(0),
    'totalMarginUsed': Decimal(0),
    'totalNtlPos': Decimal(0),
    'totalRawUsd': Decimal(0),
  }
  c = cross_collateral(state, spot_equity=Decimal('0'), free_collateral=Decimal('0'))
  assert c.leverage == Decimal('0')
  assert c.maintenance_ratio == Decimal('Infinity')


def test_isolated_collateral_math() -> None:
  """Isolated bucket: equity=rawUsd+uPnL, mm=positionValue/(2*maxLev), all non-None."""
  i = isolated_collateral(isolated_position(), LEVERAGE)
  assert i.equity == Decimal('620')  # 500 + 120
  assert i.maintenance_margin == Decimal('50')  # 5000 / (2 * 50)
  assert i.free_collateral == Decimal('120')  # max(620 - 500, 0)
  assert i.leverage == Decimal('10')
  assert i.margin_mode == 'isolated'


def test_isolated_collateral_without_a_liquidation_price() -> None:
  """A position the venue reports no `liquidationPx` for still yields a bucket.

  The maintenance margin is reconstructed from `positionValue` and `maxLeverage`,
  never back-solved from `liquidationPx`, so a null one changes nothing.
  """
  i = isolated_collateral(isolated_position(liquidation_px=None), LEVERAGE)
  assert i.equity == Decimal('620')
  assert i.maintenance_margin == Decimal('50')
