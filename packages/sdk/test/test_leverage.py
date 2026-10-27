"""Account leverage routing and the default available notional built on it."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast

from tribulnation.sdk.market import (
  Balance,
  Market,
  PerpCollateral,
  PerpMarket,
  SpotMarket,
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
  market.leverage.assert_awaited_once_with(ttl=None)
  market.collateral.assert_awaited_once_with(ttl=None)


async def test_perp_default_fails_before_reading_collateral_without_leverage():
  """An unsupported `leverage()` raises without an account read."""
  market = SimpleNamespace(
    id='x:perp:BTC',
    collateral=AsyncMock(return_value=bucket('80')),
  )
  market.leverage = lambda **kw: PerpMarket.leverage(cast(Any, market), **kw)
  with pytest.raises(NotImplementedError, match='leverage'):
    await PerpMarket.available_notional(cast(Any, market))
  market.collateral.assert_not_awaited()


def test_spot_markets_have_no_margin_stand_ins():
  """Spot sizes on `balances()`, not a quote-only notional (ADR 0051)."""
  for name in ('available_notional', 'collateral', 'position', 'leverage'):
    assert not hasattr(Market, name) and not hasattr(SpotMarket, name)


async def test_leverage_routing_preserves_ttl():
  """Root, venue and exchange calls reach the exact perpetual market and `ttl`."""
  call = AsyncMock(return_value=Decimal(10))
  target = SimpleNamespace(leverage=call)
  ttl = timedelta(seconds=30)
  for method, router, identifier in (
    (TradingMarkets.leverage, 'perp_market', 'hl:perp:BTC'),
    (TradingVenue.leverage, 'perp_market', 'perp:BTC'),
    (PerpExchange.leverage, 'market', 'BTC'),
  ):
    resolve = AsyncMock(return_value=target)
    stub = SimpleNamespace(**{router: resolve})
    assert await method(cast(Any, stub), identifier, ttl=ttl) == 10
    resolve.assert_awaited_once_with(identifier)
  assert [c.kwargs for c in call.call_args_list] == [{'ttl': ttl}] * 3


@pytest.mark.parametrize(
  'name', ['position', 'perp_position', 'available_notional', 'next_funding']
)
async def test_margin_reads_route_ttl(name: str):
  """Venue and exchange shortcuts hand the caller's `ttl` to the market."""
  call = AsyncMock(return_value=None)
  target = SimpleNamespace(**{name: call})
  ttl = timedelta(seconds=1)
  for method, router, identifier in (
    (getattr(TradingMarkets, name), 'perp_market', 'hl:perp:BTC'),
    (getattr(TradingVenue, name), 'perp_market', 'perp:BTC'),
    (getattr(PerpExchange, name), 'market', 'BTC'),
  ):
    stub = SimpleNamespace(**{router: AsyncMock(return_value=target)})
    await method(cast(Any, stub), identifier, ttl=ttl)
  assert [c.kwargs for c in call.call_args_list] == [{'ttl': ttl}] * 3


async def test_collateral_ids_resolve_with_ttl():
  """`collateral(id)` passes `ttl` to the pool or spot balance it resolves."""
  ttl = timedelta(seconds=1)
  pool = SimpleNamespace(collateral=AsyncMock(return_value=bucket('80')))
  balance = AsyncMock(return_value=Balance(total=Decimal(5), free=Decimal(4)))
  spot = SimpleNamespace(balance=balance)
  venue = SimpleNamespace(
    perp_exchange=AsyncMock(return_value=pool),
    spot_exchange=AsyncMock(return_value=spot),
  )
  await TradingVenue.collateral(cast(Any, venue), 'perp', ttl=ttl)
  await TradingVenue.collateral(cast(Any, venue), 'spot:USDC', ttl=ttl)
  pool.collateral.assert_awaited_once_with(ttl=ttl)
  balance.assert_awaited_once_with('USDC', ttl=ttl)
