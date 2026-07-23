"""Tests for bounded dYdX reporting history."""

from datetime import datetime, timedelta, timezone
from typing import Any, cast
import asyncio

from tribulnation.dydx.report.history.block_time import MemoryBlockTimeCache
from tribulnation.dydx.report.history.chain import ChainHistory
from tribulnation.dydx.report.history.main import History
from tribulnation.dydx.report.history.window import in_window

BASE_TIME = datetime(2025, 1, 1, tzinfo=timezone.utc)

class EmptyPaging:
  """One-page empty Comet search."""
  init = 0

  async def next(self, state):
    return [], None

class FakeComet:
  """Comet stub exposing deterministic block times and search queries."""
  def __init__(self, latest_height: int = 16):
    self.latest_height = latest_height
    self.block_calls = []
    self.queries = []

  async def __aenter__(self):
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    pass

  async def block(self, height=None):
    height = self.latest_height if height is None else height
    self.block_calls.append(height)
    return {'block': {'header': {
      'height': str(height),
      'time': BASE_TIME + timedelta(minutes=height),
    }}}

  def tx_search_paged(self, query, *, per_page=None):
    self.queries.append((query, per_page))
    return EmptyPaging()

def chain_history(comet: FakeComet) -> ChainHistory:
  """Create chain history around a Comet stub."""
  return ChainHistory(
    address='dydx1test',
    comet=cast(Any, comet),
    block_time_cache=MemoryBlockTimeCache(),
  )

def test_chain_resolves_inclusive_time_window_and_reuses_cache():
  comet = FakeComet()
  history = chain_history(comet)

  window = asyncio.run(history.height_window(
    BASE_TIME + timedelta(minutes=5, seconds=30),
    BASE_TIME + timedelta(minutes=10),
  ))
  first_calls = list(comet.block_calls)
  repeated = asyncio.run(history.height_window(
    BASE_TIME + timedelta(minutes=5, seconds=30),
    BASE_TIME + timedelta(minutes=10),
  ))

  assert window == (6, 10)
  assert repeated == window
  assert comet.block_calls[len(first_calls):] == [16]

def test_chain_adds_resolved_heights_to_every_search():
  comet = FakeComet()
  history = chain_history(comet)

  transactions = asyncio.run(history.fetch_transactions(
    BASE_TIME + timedelta(minutes=6),
    BASE_TIME + timedelta(minutes=10),
  ))

  assert transactions == {}
  assert len(comet.queries) == 4
  assert all('tx.height >= 6' in query for query, _ in comet.queries)
  assert all('tx.height <= 10' in query for query, _ in comet.queries)

def test_chain_skips_search_for_window_after_latest_block():
  comet = FakeComet()
  history = chain_history(comet)

  transactions = asyncio.run(history.fetch_transactions(
    BASE_TIME + timedelta(days=1),
    None,
  ))

  assert transactions == {}
  assert comet.queries == []

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
