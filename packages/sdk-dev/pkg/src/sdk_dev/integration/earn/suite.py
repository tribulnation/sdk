"""Live conformance tests for earn implementations."""

import pytest

from .support import EarnResult


def test_instruments_can_be_fetched(earn_result: EarnResult):
  """Fetch instruments without an implementation or transport error."""
  if earn_result.failure is not None:
    pytest.fail(earn_result.failure, pytrace=False)


def test_instruments_not_empty(earn_result: EarnResult):
  """Return at least one earn instrument."""
  if earn_result.failure is not None:
    pytest.skip('Fetch test failed for this account')
  assert earn_result.instruments, 'No instruments found'
