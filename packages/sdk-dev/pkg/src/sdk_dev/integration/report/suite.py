"""Live conformance tests for report implementations.

Assertion messages name observation types, assets and counts, never the account: the
parametrized id is the configuration key, which is all a report needs to say.
"""

from datetime import datetime

import pytest

from tribulnation.sdk.reporting import HistoryRecord
from .support import ReportResult

MEXC_SOURCES = {'spot_trade', 'crypto_deposit', 'crypto_withdrawal', 'funding'}
"""The observation types MEXC's `history()` is implemented to emit."""


def aware(time: datetime | None) -> bool:
  """Whether a time is present and carries a timezone."""
  return time is not None and time.tzinfo is not None


def times(record: HistoryRecord) -> list[datetime]:
  """Every observation time a record carries."""
  return [o.time for o in record.observations if o.time is not None]


def test_snapshot_can_be_fetched(report_result: ReportResult):
  """Fetch the snapshot without an implementation or transport error."""
  if report_result.snapshot_failure is not None:
    pytest.fail(report_result.snapshot_failure, pytrace=False)


def test_snapshot_time_is_tz_aware(report_result: ReportResult):
  """The snapshot's time carries a timezone."""
  if report_result.snapshot is None:
    pytest.skip('Snapshot fetch test failed for this account')
  assert aware(report_result.snapshot.snapshot.time), 'Snapshot time is naive'


def test_snapshot_balances_are_non_negative(report_result: ReportResult):
  """Every balance in every subaccount is a non-negative quantity."""
  if report_result.snapshot is None:
    pytest.skip('Snapshot fetch test failed for this account')
  negative = [
    (sub.subaccount, asset)
    for sub in report_result.snapshot.snapshot.subaccounts
    for asset, balance in sub.balances.items()
    if balance < 0
  ]
  assert not negative, f'Negative balances: {negative}'


def test_history_can_be_fetched(report_result: ReportResult):
  """Stream the last 30 days without an implementation or transport error."""
  if report_result.history_failure is not None:
    pytest.fail(report_result.history_failure, pytrace=False)


def test_history_times_are_tz_aware_and_within_bounds(report_result: ReportResult):
  """Every timed observation is tz-aware and falls inside the requested window."""
  if report_result.records is None:
    pytest.skip('History fetch test failed for this account')
  naive = [
    o.type
    for record in report_result.records
    for o in record.observations
    if o.time is not None and o.time.tzinfo is None
  ]
  assert not naive, f'Naive observation times on: {sorted(set(naive))}'
  outside = [
    (o.type, o.time)
    for record in report_result.records
    for o in record.observations
    if o.time is not None and not report_result.start <= o.time <= report_result.end
  ]
  assert not outside, f'Observations outside the window: {outside[:5]}'


def test_history_provenance_is_valid(report_result: ReportResult):
  """Every record carries a provenance with a source, an id and, for APIs, a service."""
  if report_result.records is None:
    pytest.skip('History fetch test failed for this account')
  for record in report_result.records:
    provenance = record.provenance
    assert provenance['id'], 'Record without a provenance id'
    assert provenance['source'] in {'api', 'tabular', 'manual', 'derived'}
    if provenance['source'] == 'api':
      assert provenance['service'], 'API provenance without a service'


def test_mexc_history_sources(report_result: ReportResult):
  """MEXC emits only the sources it implements, and at least one when there is any."""
  if report_result.venue != 'mexc':
    pytest.skip('MEXC-specific')
  if report_result.records is None:
    pytest.skip('History fetch test failed for this account')
  seen = {o.type for record in report_result.records for o in record.observations}
  if not seen:
    pytest.skip('The account has no MEXC history in the last 30 days')
  unexpected = seen - MEXC_SOURCES
  assert not unexpected, f'Unimplemented MEXC sources emitted: {sorted(unexpected)}'
