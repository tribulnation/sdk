"""Tests for dYdX ticker depth settings."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock
from typing_extensions import Awaitable, Callable, TypedDict, cast

from tribulnation.dydx.market.impl.mixin import ExchangeMixin
from tribulnation.sdk.market import Book, Settings


def book() -> Book:
  """Build a small deterministic order book."""
  return Book(
    bids=[Book.Entry(price=Decimal('99'), qty=Decimal('2'))],
    asks=[Book.Entry(price=Decimal('101'), qty=Decimal('3'))],
  )


def tracking_fetch() -> tuple[Callable[..., Awaitable[Book]], Callable[[], int]]:
  """Build a fetch function that reports peak concurrency."""
  active = 0
  peak = 0

  async def fetch(*_args: object) -> Book:
    nonlocal active, peak
    active += 1
    peak = max(peak, active)
    await asyncio.sleep(0.01)
    active -= 1
    return book()

  return fetch, lambda: peak


class MarketFields(TypedDict):
  """The subset of `PerpetualMarket` fields `stats.tickers` reads."""

  oraclePrice: str
  volume24H: str


@pytest.mark.parametrize('method', ['tickers', 'perp_stats'])
async def test_empty_selection_never_calls_indexer(method: str):
  """Explicitly empty bulk reads do not spend API quota or fail during an outage."""
  from tribulnation.dydx.market.impl import stats

  load = AsyncMock(side_effect=AssertionError('unexpected indexer request'))
  target = cast(
    ExchangeMixin, SimpleNamespace(shared=SimpleNamespace(load_markets=load))
  )
  assert await getattr(stats, method)(target, markets=[]) == {}
  load.assert_not_awaited()


@pytest.mark.parametrize('concurrency', [0, -1])
async def test_invalid_ticker_concurrency_rejected(concurrency: int):
  """Zero concurrency must fail instead of deadlocking the entire ticker call."""
  from tribulnation.dydx.market.impl import stats

  load = AsyncMock(return_value={'BTC-USD': {}})
  target = cast(
    ExchangeMixin, SimpleNamespace(shared=SimpleNamespace(load_markets=load))
  )
  with pytest.raises(ValueError, match='must be positive'):
    await stats.tickers(
      target, settings={'dydx': {'tickers_depth_concurrent': concurrency}}
    )


@pytest.mark.parametrize(
  ('settings', 'expected'),
  [
    ({}, 20),
    ({'dydx': {'tickers_fetch_depth': True, 'tickers_depth_concurrent': 2}}, 2),
    ({'dydx': {'tickers_fetch_depth': False}}, 0),
  ],
)
async def test_tickers_depth_concurrency(
  monkeypatch: pytest.MonkeyPatch, settings: Settings, expected: int
) -> None:
  """Apply dYdX depth fetching and concurrency settings."""
  from tribulnation.dydx.market.impl import stats

  count = 25
  markets: dict[str, MarketFields] = {
    f'MARKET-{i}': {'oraclePrice': '100', 'volume24H': '10'} for i in range(count)
  }

  class Shared:
    async def load_markets(self, *, refetch: bool = False) -> dict[str, MarketFields]:
      assert refetch
      return markets

  fetch, peak = tracking_fetch()
  monkeypatch.setattr(stats, 'fetch_order_book', fetch)

  target = cast(ExchangeMixin, SimpleNamespace(shared=Shared()))
  result = await stats.tickers(target, settings=settings)

  assert len(result) == count
  assert peak() == expected
  assert all(ticker.last is None for ticker in result.values())
  assert all(ticker.base_volume_24h is None for ticker in result.values())
  if expected:
    assert all(ticker.bid == Decimal('99') for ticker in result.values())
  else:
    assert all(
      ticker.bid is None
      and ticker.ask is None
      and ticker.bid_qty is None
      and ticker.ask_qty is None
      for ticker in result.values()
    )
