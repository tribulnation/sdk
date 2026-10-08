"""Account leverage routing and the default available notional built on it."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast

from tribulnation.sdk.market import (
  Collateral,
  Market,
  PerpCollateral,
  PerpMarket,
  TradingMarkets,
)
from tribulnation.sdk.market.exchange import PerpExchange
from tribulnation.sdk.market.venue import TradingVenue


def bucket(free: str) -> PerpCollateral:
  """A cross bucket with the given free collateral."""
  return PerpCollateral(
    equity=Decimal(100),
    free_collateral=Decimal(free),
    initial_margin=Decimal(100) - Decimal(free),
    maintenance_margin=Decimal(5),
    leverage=Decimal(1),
    margin_mode='cross',
  )


async def test_perp_default_is_free_collateral_times_leverage():
  """`collateral().free_collateral * leverage()`, with the mode-aware collateral."""
  market = SimpleNamespace(
    leverage=AsyncMock(return_value=Decimal(5)),
    collateral=AsyncMock(return_value=bucket('80')),
  )
  assert await PerpMarket.available_notional(cast(Any, market)) == Decimal(400)
  market.leverage.assert_awaited_once_with()


async def test_perp_default_fails_before_reading_collateral_without_leverage():
  """An unsupported `leverage()` raises without an account read."""
  market = SimpleNamespace(
    id='x:perp:BTC',
    collateral=AsyncMock(return_value=bucket('80')),
  )
  market.leverage = lambda: PerpMarket.leverage(cast(Any, market))
  with pytest.raises(NotImplementedError, match='leverage'):
    await PerpMarket.available_notional(cast(Any, market))
  market.collateral.assert_not_awaited()


async def test_spot_default_is_the_free_collateral():
  """Spot has no leverage: the free part of the quote bucket."""
  collateral = Collateral(equity=Decimal(50), free_collateral=Decimal(30))
  market = SimpleNamespace(collateral=AsyncMock(return_value=collateral))
  assert await Market.available_notional(cast(Any, market)) == Decimal(30)


async def test_leverage_routing_preserves_refetch():
  """Root, venue and exchange calls reach the exact perpetual market and flag."""
  call = AsyncMock(return_value=Decimal(10))
  target = SimpleNamespace(leverage=call)
  for method, router, identifier in (
    (TradingMarkets.leverage, 'perp_market', 'hl:perp:BTC'),
    (TradingVenue.leverage, 'perp_market', 'perp:BTC'),
    (PerpExchange.leverage, 'market', 'BTC'),
  ):
    resolve = AsyncMock(return_value=target)
    stub = SimpleNamespace(**{router: resolve})
    assert await method(cast(Any, stub), identifier, refetch=True) == 10
    resolve.assert_awaited_once_with(identifier)
  assert [c.kwargs for c in call.call_args_list] == [{'refetch': True}] * 3
