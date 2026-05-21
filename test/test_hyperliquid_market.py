"""Live Hyperliquid market tests."""

import os
from decimal import Decimal

import pytest

from tribulnation.hyperliquid import HyperliquidMarket

from conftest import load_venue_env
from test_market import MarketTestPlan, test_market


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
