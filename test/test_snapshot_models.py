from datetime import datetime, timezone
from decimal import Decimal
import asyncio

import pytest
from tribulnation.sdk.reporting import (
  Position, Record, Report, Snapshot, SnapshotResult, SubaccountSnapshot,
)


class StubReport(Report):
  snapshot_calls = 0

  async def history(self, start=None, end=None):
    yield Record(provenance={'source': 'manual', 'id': 'history'})

  async def snapshot(self, assets=None):
    self.snapshot_calls += 1
    return SnapshotResult(
      snapshot=Snapshot(subaccounts=[SubaccountSnapshot(subaccount='spot')]),
      provenance={'source': 'api', 'service': 'stub', 'id': 'snapshot'},
    )


async def collect_records(report: Report, *, end=None):
  return [record async for record in report.records(end=end)]


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
  assert snapshot.positions['BTC-USD'] == Position(size=Decimal('3'), avg_price=Decimal('120'))
  assert Snapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_snapshot_rejects_duplicate_subaccount_identifiers():
  with pytest.raises(ValueError, match='must be unique'):
    Snapshot(subaccounts=[
      SubaccountSnapshot(subaccount='spot'),
      SubaccountSnapshot(subaccount='spot'),
    ])


def test_snapshot_defaults_are_not_shared():
  first = Snapshot(subaccounts=[SubaccountSnapshot()])
  second = Snapshot(subaccounts=[SubaccountSnapshot()])
  first.subaccounts[0].balances['USDC'] = Decimal('1')
  assert second.subaccounts[0].balances == {}


def test_open_ended_report_wraps_snapshot_with_its_provenance():
  report = StubReport()
  records = asyncio.run(collect_records(report))
  assert len(records) == 2
  assert records[-1].provenance['source'] == 'api'
  assert records[-1].snapshots[0].subaccounts[0].subaccount == 'spot'
  assert report.snapshot_calls == 1


def test_bounded_report_does_not_fetch_snapshot():
  report = StubReport()
  records = asyncio.run(collect_records(report, end=datetime.now(timezone.utc)))
  assert len(records) == 1
  assert report.snapshot_calls == 0
