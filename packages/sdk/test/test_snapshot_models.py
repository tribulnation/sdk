from datetime import datetime, timezone
from decimal import Decimal
import asyncio

import pytest
from tribulnation.sdk.reporting import (
  Position,
  HistoryRecord,
  Report,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)


class StubReport(Report):
  snapshot_calls = 0

  async def history(self, start=None, end=None):
    yield HistoryRecord(provenance={'source': 'manual', 'id': 'history'})

  async def snapshot(self, assets=None):
    self.snapshot_calls += 1
    return SnapshotRecord(
      snapshot=Snapshot(subaccounts=[SubaccountSnapshot(subaccount='spot')]),
      provenance={'source': 'api', 'service': 'stub', 'id': 'snapshot'},
    )


async def collect_history(report: Report, *, end=None):
  return [record async for record in report.history(None, end)]


def test_snapshot_aggregates_subaccount_state_and_round_trips_json():
  snapshot = Snapshot(
    time=datetime(2025, 1, 1, tzinfo=timezone.utc),
    subaccounts=[
      SubaccountSnapshot(
        subaccount=None,
        balances={'USDC': Decimal('2')},
        positions={'BTC-USD': Position(size=Decimal('1'), avg_price=Decimal('100'))},
      ),
      SubaccountSnapshot(
        subaccount='futures',
        balances={'USDC': Decimal('3'), 'BTC': Decimal('0.1')},
        positions={'BTC-USD': Position(size=Decimal('2'), avg_price=Decimal('130'))},
      ),
    ],
  )

  assert snapshot.balances == {'USDC': Decimal('5'), 'BTC': Decimal('0.1')}
  assert snapshot.positions['BTC-USD'] == Position(
    size=Decimal('3'), avg_price=Decimal('120')
  )
  assert Snapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_snapshot_rejects_duplicate_subaccount_identifiers():
  with pytest.raises(ValueError, match='must be unique'):
    Snapshot(
      subaccounts=[
        SubaccountSnapshot(subaccount='spot'),
        SubaccountSnapshot(subaccount='spot'),
      ]
    )


def test_snapshot_defaults_are_not_shared():
  first = Snapshot(subaccounts=[SubaccountSnapshot()])
  second = Snapshot(subaccounts=[SubaccountSnapshot()])
  first.subaccounts[0].balances['USDC'] = Decimal('1')
  assert second.subaccounts[0].balances == {}


def test_history_never_fetches_a_snapshot():
  report = StubReport()
  records = asyncio.run(collect_history(report))
  assert len(records) == 1
  assert records[0].provenance['source'] == 'manual'
  assert report.snapshot_calls == 0
  assert not hasattr(report, 'records')


def test_snapshot_record_carries_a_single_snapshot_and_its_provenance():
  report = StubReport()
  result = asyncio.run(report.snapshot())
  assert isinstance(result, SnapshotRecord)
  assert result.provenance['source'] == 'api'
  assert result.snapshot.subaccounts[0].subaccount == 'spot'
  assert report.snapshot_calls == 1
