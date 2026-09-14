"""Live snapshot conformance tests for report implementations.

Assertion messages name observation types, assets and counts, never the account: the
parametrized id is the configuration key, which is all a report needs to say.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from .support import ReportResult


def aware(time: datetime | None) -> bool:
  """Whether a time is present and carries a timezone."""
  return time is not None and time.utcoffset() is not None


def test_snapshot_can_be_fetched(report_result: ReportResult):
  """Fetch the snapshot without an implementation or transport error."""
  if report_result.snapshot_failure is not None:
    pytest.fail(report_result.snapshot_failure, pytrace=False)


def test_snapshot_time_is_tz_aware(report_result: ReportResult):
  """The snapshot's time carries a timezone."""
  if report_result.snapshot is None:
    pytest.skip('Snapshot fetch test failed for this account')
  assert aware(report_result.snapshot.snapshot.time), 'Snapshot time is naive'


def test_snapshot_balances_are_finite_decimals(report_result: ReportResult):
  """Signed balances are valid; every quantity must be a finite Decimal."""
  if report_result.snapshot is None:
    pytest.skip('Snapshot fetch test failed for this account')
  for sub in report_result.snapshot.snapshot.subaccounts:
    for balance in sub.balances.values():
      assert isinstance(balance, Decimal) and balance.is_finite(), (
        'Invalid balance quantity'
      )
