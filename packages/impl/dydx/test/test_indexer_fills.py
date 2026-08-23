"""Tests for ordered dYdX indexer fills and realized PnL."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import Any, cast

import pytest
from typed_dydx.indexer.data.get_fills import Fill
from sqlalchemy.orm import Session
from tribulnation.dydx.report.history.cache import (
  CacheWatermark,
  HistoryCache,
  IndexerFill,
)
from tribulnation.dydx.report.history.indexer import (
  IndexerHistory,
  ReplayPosition,
  parse_fills,
)
from tribulnation.dydx.report.main import normalize_perpetual_collateral
from tribulnation.sdk.reporting import Position, Snapshot, SubaccountSnapshot

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fill(
  id: str,
  *,
  minute: int,
  side: str,
  size: str,
  price: str,
  market: str = 'BTC-USD',
  height: int | None = None,
) -> Fill:
  """Create a typed fill fixture."""
  return cast(
    Fill,
    {
      'id': id,
      'side': side,
      'liquidity': 'TAKER',
      'type': 'LIMIT',
      'market': market,
      'marketType': 'PERPETUAL',
      'price': Decimal(price),
      'size': Decimal(size),
      'fee': Decimal('0.01'),
      'affiliateRevShare': Decimal(0),
      'createdAt': BASE_TIME + timedelta(minutes=minute),
      'createdAtHeight': str(height if height is not None else minute + 1),
      'orderId': f'order-{id}',
      'subaccountNumber': 0,
    },
  )


class FakePaging:
  """Deterministic page-number iterator."""

  init = 0

  def __init__(self, pages: list[list[Fill]], *, fail: bool = False):
    self.pages = pages
    self.fail = fail

  async def next(self, page: int):
    """Return one configured page."""
    if self.fail:
      raise RuntimeError('fill fetch failed')
    rows = self.pages[page]
    next_page = page + 1 if page + 1 < len(self.pages) else None
    return rows, next_page


class FakeIndexerData:
  """Indexer data stub that pages newest-first fills."""

  def __init__(self, fills: list[Fill], *, indexed_through: datetime):
    self.fills = fills
    self.indexed_through = indexed_through
    self.fetches = 0
    self.fail = False

  async def get_height(self):
    """Return the configured indexed time."""
    return {'height': '100', 'time': self.indexed_through}

  def get_fills_paged(
    self,
    address: str,
    *,
    subaccount: int,
    created_before_or_at: datetime | None = None,
  ):
    """Return fixed-size pages in endpoint order."""
    del address, subaccount
    self.fetches += 1
    rows = [
      row
      for row in self.fills
      if created_before_or_at is None or row['createdAt'] <= created_before_or_at
    ]
    pages = [rows[index : index + 2] for index in range(0, len(rows), 2)]
    pages.append([])
    return FakePaging(pages, fail=self.fail)


class FakeIndexer:
  """Indexer stub exposing data endpoints."""

  def __init__(self, data: FakeIndexerData):
    self.data = data


def history(data: FakeIndexerData, cache: HistoryCache | None = None) -> IndexerHistory:
  """Create indexer history around a stub."""
  return IndexerHistory(
    address='dydx1test',
    indexer=cast(Any, FakeIndexer(data)),
    cache=cache,
  )


def test_parse_fills_preserves_tied_execution_order():
  """Tied fills use stream order rather than UUID order."""
  opening = fill('open', minute=0, side='BUY', size='1', price='100')
  increase = fill('z-increase', minute=1, side='BUY', size='1', price='90')
  reduce = fill('a-reduce', minute=1, side='SELL', size='1', price='110')

  trades = parse_fills([opening, increase, reduce])

  assert [trade.id for trade in trades] == ['open', 'z-increase', 'a-reduce']
  assert [trade.realized_pnl for trade in trades] == [
    Decimal(0),
    Decimal(0),
    Decimal(15),
  ]


def test_parse_fills_handles_short_reductions_and_flips():
  """Replay closes only the opposing portion and resets flips at fill price."""
  trades = parse_fills(
    [
      fill('short', minute=0, side='SELL', size='2', price='100'),
      fill('partial', minute=1, side='BUY', size='1', price='80'),
      fill('flip', minute=2, side='BUY', size='2', price='90'),
      fill('close-long', minute=3, side='SELL', size='1', price='110'),
    ]
  )

  assert [trade.realized_pnl for trade in trades] == [
    Decimal(0),
    Decimal(20),
    Decimal(10),
    Decimal(20),
  ]


def test_parse_fills_weights_increases_by_remaining_position():
  """Entry price uses the remaining position after partial reductions."""
  trades = parse_fills(
    [
      fill('open', minute=0, side='BUY', size='2', price='100'),
      fill('reduce', minute=1, side='SELL', size='1', price='110'),
      fill('increase', minute=2, side='BUY', size='1', price='80'),
      fill('close', minute=3, side='SELL', size='2', price='100'),
    ]
  )

  assert [trade.realized_pnl for trade in trades] == [
    Decimal(0),
    Decimal(10),
    Decimal(0),
    Decimal(20),
  ]


def test_snapshot_collateral_uses_replayed_position_basis():
  """Collateral and realized PnL use the same average-cost convention."""
  snapshot = Snapshot(
    time=BASE_TIME,
    subaccounts=[
      SubaccountSnapshot(
        subaccount='0',
        balances={'USDC': Decimal(100)},
        positions={
          'BTC-USD': Position(size=Decimal(2), avg_price=Decimal(90)),
        },
      ),
    ],
  )

  normalized = normalize_perpetual_collateral(
    snapshot,
    {
      '0': {
        'BTC-USD': ReplayPosition(
          signed_size=Decimal(2),
          entry_price=Decimal(95),
        ),
      },
    },
  )

  assert normalized.subaccounts[0].balances['USDC'] == Decimal(110)
  assert normalized.subaccounts[0].positions == snapshot.subaccounts[0].positions


def test_parse_fills_rejects_non_chronological_input():
  """The parser refuses to invent an execution order."""
  with pytest.raises(ValueError, match='chronological order'):
    parse_fills(
      [
        fill('later', minute=2, side='BUY', size='1', price='100'),
        fill('earlier', minute=1, side='SELL', size='1', price='100'),
      ]
    )


def test_fetch_reverses_endpoint_pages_and_persists_sequence(tmp_path):
  """A full newest-first response is cached and replayed chronologically."""
  newest_first = [
    fill('third', minute=2, side='SELL', size='1', price='110'),
    fill('second', minute=1, side='BUY', size='1', price='90'),
    fill('first', minute=0, side='BUY', size='1', price='100'),
  ]
  data = FakeIndexerData(
    newest_first,
    indexed_through=BASE_TIME + timedelta(minutes=3),
  )
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')
  report = history(data, cache)

  fetched = asyncio.run(report.fetch_fills(subaccount=0))
  repeated = asyncio.run(report.fetch_fills(subaccount=0))

  assert [row['id'] for row in fetched] == ['first', 'second', 'third']
  assert repeated == fetched
  assert data.fetches == 1
  assert cache.indexer_fill_coverage(
    report.address,
    0,
  ) == BASE_TIME + timedelta(minutes=3)


def test_fetch_preserves_ascending_endpoint_pages():
  """A bounded endpoint response already in chronological order is retained."""
  oldest_first = [
    fill('first', minute=0, side='BUY', size='1', price='100'),
    fill('second', minute=1, side='BUY', size='1', price='90'),
    fill('third', minute=2, side='SELL', size='1', price='110'),
  ]
  data = FakeIndexerData(
    oldest_first,
    indexed_through=BASE_TIME + timedelta(minutes=3),
  )

  fetched = asyncio.run(history(data).fetch_fills(subaccount=0))

  assert [row['id'] for row in fetched] == ['first', 'second', 'third']


def test_fetch_extends_coverage_with_full_atomic_refresh(tmp_path):
  """Extending a genesis prefix replaces the complete sequenced stream."""
  first = fill('first', minute=0, side='BUY', size='1', price='100')
  data = FakeIndexerData(
    [first],
    indexed_through=BASE_TIME + timedelta(minutes=1),
  )
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')
  report = history(data, cache)
  asyncio.run(report.fetch_fills(subaccount=0))

  second = fill('second', minute=1, side='SELL', size='1', price='110')
  data.fills = [second, first]
  data.indexed_through = BASE_TIME + timedelta(minutes=2)
  refreshed = asyncio.run(report.fetch_fills(subaccount=0))

  assert [row['id'] for row in refreshed] == ['first', 'second']
  assert data.fetches == 2
  assert cache.indexer_fill_coverage(
    report.address,
    0,
  ) == BASE_TIME + timedelta(minutes=2)


def test_fetch_failure_keeps_previous_fills_and_coverage(tmp_path):
  """A failed refresh does not claim coverage or replace good rows."""
  first = fill('first', minute=0, side='BUY', size='1', price='100')
  data = FakeIndexerData(
    [first],
    indexed_through=BASE_TIME + timedelta(minutes=1),
  )
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')
  report = history(data, cache)
  asyncio.run(report.fetch_fills(subaccount=0))

  data.indexed_through = BASE_TIME + timedelta(minutes=2)
  data.fail = True
  with pytest.raises(Exception, match='fill fetch failed'):
    asyncio.run(report.fetch_fills(subaccount=0))

  assert [
    row['id']
    for row in cache.read_indexer_fills(
      report.address,
      0,
    )
  ] == ['first']
  assert cache.indexer_fill_coverage(
    report.address,
    0,
  ) == BASE_TIME + timedelta(minutes=1)


def test_fetch_ignores_legacy_indexer_watermark_and_rows(tmp_path):
  """Legacy unsequenced cache state does not imply genesis coverage."""
  legacy = fill('legacy', minute=0, side='BUY', size='1', price='100')
  current = fill('current', minute=1, side='SELL', size='1', price='110')
  data = FakeIndexerData(
    [current],
    indexed_through=BASE_TIME + timedelta(minutes=2),
  )
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')
  with Session(cache.engine) as session:
    session.add(
      IndexerFill(
        address='dydx1test',
        subaccount=0,
        fill_id=legacy['id'],
        created_at_height=1,
        data=legacy,
      )
    )
    session.add(
      CacheWatermark(
        source='indexer',
        address='dydx1test/0',
        height=1,
      )
    )
    session.commit()

  fetched = asyncio.run(history(data, cache).fetch_fills(subaccount=0))

  assert [row['id'] for row in fetched] == ['current']
  assert data.fetches == 1


def test_start_is_applied_after_replay_from_genesis(tmp_path):
  """A bounded output obtains its position basis from earlier fills."""
  newest_first = [
    fill('close', minute=2, side='SELL', size='1', price='110'),
    fill('increase', minute=1, side='BUY', size='1', price='90'),
    fill('open', minute=0, side='BUY', size='1', price='100'),
  ]
  data = FakeIndexerData(
    newest_first,
    indexed_through=BASE_TIME + timedelta(minutes=3),
  )
  cache = HistoryCache.connect(f'sqlite:///{tmp_path / "cache.db"}')

  trades = asyncio.run(
    history(data, cache).fills(
      subaccount=0,
      start=BASE_TIME + timedelta(minutes=2),
    )
  )

  assert [trade.id for trade in trades] == ['close']
  assert trades[0].realized_pnl == Decimal(15)
