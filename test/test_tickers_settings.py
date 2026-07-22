import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, Awaitable, Callable, cast

import pytest

from tribulnation.sdk.market import Book


def _book() -> Book:
  return Book(
    bids=[Book.Entry(price=Decimal('99'), qty=Decimal('2'))],
    asks=[Book.Entry(price=Decimal('101'), qty=Decimal('3'))],
  )


def _tracking_fetch() -> tuple[Callable[..., Awaitable[Book]], Callable[[], int]]:
  active = 0
  peak = 0

  async def fetch(*_args) -> Book:
    nonlocal active, peak
    active += 1
    peak = max(peak, active)
    await asyncio.sleep(0.01)
    active -= 1
    return _book()

  return fetch, lambda: peak


@pytest.mark.parametrize(('settings', 'expected'), [({}, 20), ({'dydx': {'tickers_depth_concurrent': 2}}, 2)])
async def test_dydx_tickers_depth_concurrency(monkeypatch, settings, expected: int) -> None:
  from tribulnation.dydx.market.impl import stats

  count = 25
  markets = {
    f'MARKET-{i}': {'oraclePrice': '100', 'volume24H': '10'}
    for i in range(count)
  }

  class Shared:
    async def load_markets(self, *, refetch: bool = False):
      assert refetch
      return markets

  fetch, peak = _tracking_fetch()
  monkeypatch.setattr(stats, 'fetch_order_book', fetch)

  target = cast(Any, SimpleNamespace(shared=Shared()))
  result = await stats.tickers(target, settings=settings)

  assert len(result) == count
  assert peak() == expected
  assert all(ticker.bid == Decimal('99') for ticker in result.values())


@pytest.mark.parametrize(
  ('settings', 'expected'),
  [({}, 20), ({'hyperliquid': {'tickers_depth_concurrent': 2}}, 2)],
)
async def test_hyperliquid_perp_tickers_depth_concurrency(monkeypatch, settings, expected: int) -> None:
  from tribulnation.hyperliquid.market.impl import stats

  count = 25
  meta = {'universe': [{'name': f'COIN-{i}'} for i in range(count)]}
  contexts = [{'midPx': '100', 'dayNtlVlm': '10'} for _ in range(count)]

  class Shared:
    async def load_perp_meta_for_dex(self, dex_name: str, *, refetch: bool = False):
      assert dex_name == ''
      assert refetch
      return None, meta, contexts

  fetch, peak = _tracking_fetch()
  monkeypatch.setattr(stats, 'fetch_l2_book', fetch)

  target = cast(Any, SimpleNamespace(shared=Shared(), dex_name=''))
  result = await stats.perp_tickers(target, settings=settings)

  assert len(result) == count
  assert peak() == expected
  assert all(ticker.ask == Decimal('101') for ticker in result.values())


@pytest.mark.parametrize(
  ('settings', 'expected'),
  [({}, 20), ({'hyperliquid': {'tickers_depth_concurrent': 2}}, 2)],
)
async def test_hyperliquid_spot_tickers_depth_concurrency(monkeypatch, settings, expected: int) -> None:
  from tribulnation.hyperliquid.market import spot_exchange

  count = 25
  spot_meta = {
    'tokens': [
      {'index': 0, 'name': 'USD'},
      *({'index': i + 1, 'name': f'COIN-{i}'} for i in range(count)),
    ],
    'universe': [
      {'index': i, 'tokens': [i + 1, 0], 'name': f'@{i}'}
      for i in range(count)
    ],
  }
  contexts = [{'midPx': '100', 'dayNtlVlm': '10'} for _ in range(count)]

  class Info:
    async def spot_meta_and_asset_ctxs(self):
      return spot_meta, contexts

  fetch, peak = _tracking_fetch()
  monkeypatch.setattr(spot_exchange, 'fetch_l2_book', fetch)

  target = cast(Any, SimpleNamespace(shared=SimpleNamespace(client=SimpleNamespace(info=Info()))))
  result = await spot_exchange.SpotExchange.tickers(target, settings=settings)

  assert len(result) == count
  assert peak() == expected
  assert all(ticker.bid_qty == Decimal('2') for ticker in result.values())
