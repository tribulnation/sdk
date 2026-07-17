"""Live Hyperliquid market tests."""

import os
from decimal import Decimal

import pytest

from tribulnation.hyperliquid import HyperliquidMarket
from tribulnation.hyperliquid.market.impl.collateral import (
  cross_collateral,
  isolated_collateral,
)

from conftest import load_venue_env
from test_market import MarketTestPlan, test_market


def _cross_state() -> dict:
  summary = {
    'accountValue': '1000',
    'totalMarginUsed': '200',
    'totalNtlPos': '3000',
    'totalRawUsd': '1000',
  }
  return {
    'crossMarginSummary': summary,
    'marginSummary': dict(summary),
    'crossMaintenanceMarginUsed': '100',
    'withdrawable': '800',
    'assetPositions': [],
    'time': 0,
  }


def _isolated_position() -> dict:
  return {
    'coin': 'BTC',
    'entryPx': '50000',
    'leverage': {'type': 'isolated', 'value': 10, 'rawUsd': '500'},
    'liquidationPx': '45000',
    'marginUsed': '500',
    'maxLeverage': 50,
    'positionValue': '5000',
    'returnOnEquity': '0',
    'szi': '0.1',
    'unrealizedPnl': '120',
    'cumFunding': {'allTime': '0', 'sinceChange': '0', 'sinceOpen': '0'},
  }


def test_cross_collateral_math() -> None:
  """Cross bucket reads straight from the venue summary; every field non-None."""
  c = cross_collateral(_cross_state(), spot_equity=Decimal('1000'), free_collateral=Decimal('800'))
  assert c.equity == Decimal('1000')
  assert c.free_collateral == Decimal('800')
  assert c.initial_margin == Decimal('200')
  assert c.maintenance_margin == Decimal('100')
  assert c.leverage == Decimal('3')  # totalNtlPos / spot_equity
  assert c.margin_mode == 'cross'
  assert c.maintenance_ratio == Decimal('0.1')


def test_cross_collateral_non_positive_equity() -> None:
  """Zero equity => 0 leverage and +Infinity maintenance_ratio (no div-by-zero)."""
  state = _cross_state()
  state['crossMarginSummary'] = {
    'accountValue': '0', 'totalMarginUsed': '0', 'totalNtlPos': '0', 'totalRawUsd': '0',
  }
  c = cross_collateral(state, spot_equity=Decimal('0'), free_collateral=Decimal('0'))
  assert c.leverage == Decimal('0')
  assert c.maintenance_ratio == Decimal('Infinity')


def test_isolated_collateral_math() -> None:
  """Isolated bucket: equity=rawUsd+uPnL, mm=positionValue/(2*maxLev), all non-None."""
  pos = _isolated_position()
  i = isolated_collateral(pos, pos['leverage'])
  assert i.equity == Decimal('620')            # 500 + 120
  assert i.maintenance_margin == Decimal('50')  # 5000 / (2 * 50)
  assert i.free_collateral == Decimal('120')    # max(620 - 500, 0)
  assert i.leverage == Decimal('10')
  assert i.margin_mode == 'isolated'


def test_public_instance_constructs() -> None:
  """A public/no-credential venue instance constructs without error."""
  venue = HyperliquidMarket.http('0x0000000000000000000000000000000000000000')
  assert venue.venue_id == 'hyperliquid'


HYPERLIQUID_TESTNET_PLAN = MarketTestPlan(
  venue='hyperliquid',
  market_id='hyperliquid_testnet::BTC',
  required_env=('HYPERLIQUID_TESTNET_ADDRESS', 'HYPERLIQUID_TESTNET_PRIVATE_KEY'),
  order_notional=Decimal('50'),
  fill_notional=Decimal('50'),
)


@pytest.mark.live
@pytest.mark.trading
async def test_hyperliquid_testnet_market_with_private_key() -> None:
  """Run live Hyperliquid testnet conformance with an explicitly signed wallet."""
  load_venue_env(
    HYPERLIQUID_TESTNET_PLAN.venue,
    required=HYPERLIQUID_TESTNET_PLAN.required_env,
  )
  venue = HyperliquidMarket.http(
    os.environ['HYPERLIQUID_TESTNET_ADDRESS'],
    wallet=os.environ['HYPERLIQUID_TESTNET_PRIVATE_KEY'],
    mainnet=False,
  )
  market = await venue.perp_market(':BTC')
  async with market:
    await test_market(market, HYPERLIQUID_TESTNET_PLAN)
