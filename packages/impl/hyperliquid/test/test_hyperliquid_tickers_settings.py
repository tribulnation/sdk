"""Tests for Hyperliquid ticker depth settings."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typing_extensions import Any, Awaitable, Callable, cast

from typed_hyperliquid.info.perp_meta_and_asset_ctxs import (
  PerpAssetContext,
  PerpDexMeta,
)
from typed_hyperliquid.info.spot_meta_and_asset_ctxs import SpotAssetCtx, SpotMeta

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


def perp_context() -> PerpAssetContext:
  """One perp asset context, priced at 100 with 10 of daily volume."""
  return {
    'dayNtlVlm': Decimal('1000'),
    'dayBaseVlm': Decimal('10'),
    'funding': Decimal(0),
    'impactPxs': None,
    'markPx': Decimal('100'),
    'midPx': Decimal('100'),
    'openInterest': Decimal(0),
    'oraclePx': Decimal('100'),
    'premium': None,
    'prevDayPx': Decimal('100'),
  }


def spot_context() -> SpotAssetCtx:
  """One spot asset context, priced at 100 with 10 of daily volume."""
  return {
    'markPx': Decimal('100'),
    'midPx': Decimal('100'),
    'prevDayPx': Decimal('100'),
    'dayNtlVlm': Decimal('1000'),
    'dayBaseVlm': Decimal('10'),
  }


@pytest.mark.parametrize(
  ('settings', 'expected'),
  [
    ({}, 20),
    ({'hyperliquid': {'tickers_fetch_depth': True, 'tickers_depth_concurrent': 2}}, 2),
    ({'hyperliquid': {'tickers_fetch_depth': False}}, 0),
  ],
)
async def test_perp_tickers_depth_concurrency(
  monkeypatch: pytest.MonkeyPatch, settings: Settings, expected: int
) -> None:
  """Apply Hyperliquid perp depth fetching and concurrency settings."""
  from tribulnation.hyperliquid.market.impl import stats

  count = 25
  meta: PerpDexMeta = {
    'collateralToken': 0,
    'marginTables': [],
    'universe': [
      {'name': f'COIN-{i}', 'maxLeverage': 5, 'szDecimals': 2} for i in range(count)
    ],
  }
  contexts = [perp_context() for _ in range(count)]
  del contexts[0]['dayBaseVlm']

  class Shared:
    async def load_perp_meta_for_dex(self, dex_name: str, *, refetch: bool = False):
      assert dex_name == ''
      assert refetch
      return None, meta, contexts

  fetch, peak = tracking_fetch()
  monkeypatch.setattr(stats, 'fetch_l2_book', fetch)

  target = cast(Any, SimpleNamespace(shared=Shared(), dex_name=''))
  result = await stats.perp_tickers(target, settings=settings)

  assert len(result) == count
  assert peak() == expected
  assert all(ticker.last is None for ticker in result.values())
  assert [ticker.base_volume_24h for ticker in result.values()] == [None] + [
    Decimal('10')
  ] * (count - 1)
  if expected:
    assert all(ticker.ask == Decimal('101') for ticker in result.values())
  else:
    assert all(
      ticker.bid is None
      and ticker.ask is None
      and ticker.bid_qty is None
      and ticker.ask_qty is None
      for ticker in result.values()
    )


@pytest.mark.parametrize(
  ('settings', 'expected'),
  [
    ({}, 20),
    ({'hyperliquid': {'tickers_fetch_depth': True, 'tickers_depth_concurrent': 2}}, 2),
    ({'hyperliquid': {'tickers_fetch_depth': False}}, 0),
  ],
)
async def test_spot_tickers_depth_concurrency(
  monkeypatch: pytest.MonkeyPatch, settings: Settings, expected: int
) -> None:
  """Apply Hyperliquid spot depth fetching and concurrency settings."""
  from tribulnation.hyperliquid.market import spot_exchange

  count = 25
  spot_meta: SpotMeta = {
    'tokens': [
      {
        'index': i,
        'name': 'USD' if i == 0 else f'COIN-{i - 1}',
        'szDecimals': 2,
        'weiDecimals': 8,
        'tokenId': f'0x{i:032x}',
        'isCanonical': True,
        'evmContract': None,
        'fullName': None,
      }
      for i in range(count + 1)
    ],
    'universe': [
      {'index': i, 'tokens': (i + 1, 0), 'name': f'@{i}', 'isCanonical': False}
      for i in range(count)
    ],
  }
  contexts = [spot_context() for _ in range(count)]
  del contexts[0]['dayBaseVlm']

  class Info:
    async def spot_meta_and_asset_ctxs(self):
      return spot_meta, contexts

  fetch, peak = tracking_fetch()
  monkeypatch.setattr(spot_exchange, 'fetch_l2_book', fetch)

  target = cast(
    Any,
    SimpleNamespace(
      shared=SimpleNamespace(client=SimpleNamespace(info=Info())),
    ),
  )
  result = await spot_exchange.SpotExchange.tickers(target, settings=settings)

  assert len(result) == count
  assert peak() == expected
  assert all(ticker.last is None for ticker in result.values())
  assert [ticker.base_volume_24h for ticker in result.values()] == [None] + [
    Decimal('10')
  ] * (count - 1)
  if expected:
    assert all(ticker.bid_qty == Decimal('2') for ticker in result.values())
  else:
    assert all(
      ticker.bid is None
      and ticker.ask is None
      and ticker.bid_qty is None
      and ticker.ask_qty is None
      for ticker in result.values()
    )
