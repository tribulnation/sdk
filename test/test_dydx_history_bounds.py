"""Tests for bounded dYdX reporting history."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from sqlalchemy.orm import Session
from tribulnation.dydx.report.history.cache import (
  CacheWatermark,
  ChainTransaction,
  HistoryCache,
)
from tribulnation.dydx.report.history.chain import ChainHistory
from tribulnation.dydx.report.history.main import History
from tribulnation.dydx.report.history.window import in_window
from typing_extensions import Any

BASE_TIME = datetime(2025, 1, 1, tzinfo=timezone.utc)


class EmptyPaging:
  """One-page empty Comet search."""

  init = 0

  def __init__(self, *, fail: bool = False):
    self.fail = fail

  async def next(self, state):
    if self.fail:
      raise RuntimeError('search failed')
    return [], None


class FakeComet:
  """Comet stub exposing deterministic block times and search queries."""

  def __init__(self, latest_height: int = 16, *, fail_pattern: str | None = None):
    self.latest_height = latest_height
    self.fail_pattern = fail_pattern
    self.block_calls = []
    self.queries = []

  async def __aenter__(self):
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    pass

  async def block(self, height=None):
    height = self.latest_height if height is None else height
    self.block_calls.append(height)
    return {
      'block': {
        'header': {
          'height': str(height),
          'time': BASE_TIME + timedelta(minutes=height),
        }
      }
    }

  def tx_search_paged(self, query, *, per_page=None):
    self.queries.append((query, per_page))
    return EmptyPaging(
      fail=(self.fail_pattern is not None and self.fail_pattern in query)
    )


def chain_history(comet: FakeComet) -> ChainHistory:
  """Create chain history around a Comet stub.

  No `cache=`, so block times are memoized in the in-process `_block_times`
  map -- which is what `..._reuses_cache` below asserts against.
  """
  return ChainHistory(
    address='dydx1test',
    comet=cast(Any, comet),
  )


def cached_chain_history(
  comet: FakeComet,
  cache: HistoryCache,
) -> ChainHistory:
  """Create chain history around a Comet stub and persistent cache."""
  return ChainHistory(
    address='dydx1test',
    comet=cast(Any, comet),
    cache=cache,
  )


def test_chain_resolves_inclusive_time_window_and_reuses_cache():
  comet = FakeComet()
  history = chain_history(comet)

  window = asyncio.run(
    history.height_window(
      BASE_TIME + timedelta(minutes=5, seconds=30),
      BASE_TIME + timedelta(minutes=10),
    )
  )
  first_calls = list(comet.block_calls)
  repeated = asyncio.run(
    history.height_window(
      BASE_TIME + timedelta(minutes=5, seconds=30),
      BASE_TIME + timedelta(minutes=10),
    )
  )

  assert window == (6, 10)
  assert repeated == window
  assert comet.block_calls[len(first_calls) :] == [16]


def test_chain_resolves_open_time_bounds_to_genesis_and_latest():
  """Open datetime bounds resolve to concrete chain heights."""
  comet = FakeComet()
  history = chain_history(comet)

  from_genesis = asyncio.run(
    history.height_window(
      None,
      BASE_TIME + timedelta(minutes=10),
    )
  )
  through_latest = asyncio.run(
    history.height_window(
      BASE_TIME + timedelta(minutes=6),
      None,
    )
  )

  assert from_genesis == (1, 10)
  assert through_latest == (6, 16)


def test_chain_adds_resolved_heights_to_every_search():
  comet = FakeComet()
  history = chain_history(comet)

  transactions = asyncio.run(
    history.fetch_transactions(
      BASE_TIME + timedelta(minutes=6),
      BASE_TIME + timedelta(minutes=10),
    )
  )

  assert transactions == {}
  assert len(comet.queries) == 4
  assert all('tx.height >= 6' in query for query, _ in comet.queries)
  assert all('tx.height <= 10' in query for query, _ in comet.queries)


def test_chain_skips_search_for_window_after_latest_block():
  comet = FakeComet()
  history = chain_history(comet)

  transactions = asyncio.run(
    history.fetch_transactions(
      BASE_TIME + timedelta(days=1),
      None,
    )
  )

  assert transactions == {}
  assert comet.queries == []


def test_chain_cache_backfills_around_bounded_coverage(tmp_path):
  """An unbounded fetch fills both sides of an initially bounded cache."""
  comet = FakeComet()
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')
  history = cached_chain_history(comet, cache)

  asyncio.run(
    history.fetch_transactions(
      BASE_TIME + timedelta(minutes=6),
      BASE_TIME + timedelta(minutes=10),
    )
  )
  assert cache.chain_coverage(history.address) == [(6, 10)]

  comet.queries.clear()
  asyncio.run(history.fetch_transactions(None, None))

  assert cache.chain_coverage(history.address) == [(1, 16)]
  assert len(comet.queries) == 8
  assert (
    sum(
      'tx.height >= 1' in query and 'tx.height <= 5' in query
      for query, _ in comet.queries
    )
    == 4
  )
  assert (
    sum(
      'tx.height >= 11' in query and 'tx.height <= 16' in query
      for query, _ in comet.queries
    )
    == 4
  )


def test_chain_cache_extends_genesis_coverage(tmp_path):
  """A later unbounded fetch requests only heights beyond verified coverage."""
  comet = FakeComet(latest_height=10)
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')
  history = cached_chain_history(comet, cache)

  asyncio.run(history.fetch_transactions(None, None))
  assert cache.chain_coverage(history.address) == [(1, 10)]

  comet.latest_height = 16
  comet.queries.clear()
  asyncio.run(history.fetch_transactions(None, None))

  assert cache.chain_coverage(history.address) == [(1, 16)]
  assert len(comet.queries) == 4
  assert all(
    'tx.height >= 11' in query and 'tx.height <= 16' in query
    for query, _ in comet.queries
  )


def test_chain_cache_records_empty_coverage(tmp_path):
  """A successful empty fetch is not repeated."""
  comet = FakeComet()
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')
  history = cached_chain_history(comet, cache)

  asyncio.run(history.fetch_transactions(None, None))
  comet.queries.clear()
  asyncio.run(history.fetch_transactions(None, None))

  assert cache.chain_coverage(history.address) == [(1, 16)]
  assert comet.queries == []


def test_chain_cache_does_not_cover_failed_fetch(tmp_path):
  """A failed provider group does not claim coverage."""
  comet = FakeComet(fail_pattern='coin_spent.spender')
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')
  history = cached_chain_history(comet, cache)

  with pytest.raises(RuntimeError, match='search failed'):
    asyncio.run(history.fetch_transactions(None, None))

  assert cache.chain_coverage(history.address) == []


def test_chain_cache_ignores_legacy_watermark(tmp_path):
  """An old high watermark does not imply verified genesis coverage."""
  comet = FakeComet()
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')
  with Session(cache.engine) as session:
    session.add(
      CacheWatermark(
        source='chain',
        address='dydx1test',
        height=10,
      )
    )
    session.add(
      ChainTransaction(
        address='dydx1test',
        tx_hash='legacy',
        height=6,
        data={'hash': 'legacy', 'height': '6'},
      )
    )
    session.commit()
  history = cached_chain_history(comet, cache)

  transactions = asyncio.run(history.fetch_transactions(None, None))

  assert cache.chain_coverage(history.address) == [(1, 16)]
  assert transactions['legacy']['height'] == '6'
  assert len(comet.queries) == 4
  assert all(
    'tx.height >= 1' in query and 'tx.height <= 16' in query
    for query, _ in comet.queries
  )


def test_chain_no_cache_reads_refetches_and_populates(tmp_path):
  """No-cache mode bypasses coverage reads but still writes coverage."""
  path = tmp_path / 'cache.db'
  initial_comet = FakeComet()
  initial_cache = HistoryCache.connect(f'sqlite:///{path}')
  asyncio.run(
    cached_chain_history(
      initial_comet,
      initial_cache,
    ).fetch_transactions(None, None)
  )

  comet = FakeComet()
  cache = HistoryCache.connect(
    f'sqlite:///{path}',
    no_cache_reads=True,
  )
  history = cached_chain_history(comet, cache)
  asyncio.run(history.fetch_transactions(None, None))

  assert len(comet.queries) == 4
  assert all(
    'tx.height >= 1' in query and 'tx.height <= 16' in query
    for query, _ in comet.queries
  )
  assert initial_cache.chain_coverage(history.address) == [(1, 16)]


class HistoryProvider:
  """History stub recording requested bounds."""

  def __init__(self):
    self.calls = []

  async def history(self, start, end):
    self.calls.append((start, end))
    return []


def test_aggregate_history_forwards_bounds_to_every_provider():
  providers = [HistoryProvider() for _ in range(4)]
  report = History(
    address='dydx1test',
    chain=cast(Any, providers[0]),
    indexer=cast(Any, providers[1]),
    governance=cast(Any, providers[2]),
    bigquery=cast(Any, providers[3]),
  )
  start = BASE_TIME
  end = BASE_TIME + timedelta(days=1)

  async def collect():
    return [record async for record in report.history(start, end)]

  assert asyncio.run(collect()) == []
  assert all(provider.calls == [(start, end)] for provider in providers)


def test_history_window_is_inclusive_and_keeps_unknown_times():
  assert in_window(BASE_TIME, start=BASE_TIME, end=BASE_TIME)
  assert in_window(None, start=BASE_TIME, end=BASE_TIME)
  assert not in_window(
    BASE_TIME - timedelta(microseconds=1),
    start=BASE_TIME,
    end=None,
  )
