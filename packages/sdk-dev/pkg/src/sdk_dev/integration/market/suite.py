"""Live conformance tests for `Market.candles` implementations."""

from decimal import Decimal

import pytest

from .support import HOUR, STRADDLE_EXTRA, WINDOW, CandleCase, CandlesResult


def check_series(result: CandlesResult, *, count: int):
  """Check the candle contract without requiring synthetic rows for venue-side gaps."""
  candles = result.candles
  assert candles, 'No candles returned for the recent reference market window'
  assert len(candles) <= count, 'More candles than hourly slots'
  opens = [c.time for c in candles]
  assert all(time.utcoffset() is not None for time in opens), 'Naive candle open'
  assert len(set(opens)) == len(opens), 'Duplicated candle opens'
  assert all(result.start <= time < result.end for time in opens), (
    'Open outside [start, end)'
  )
  assert all((time - result.start) % HOUR == HOUR * 0 for time in opens), (
    'Unaligned open'
  )
  for page in result.pages or []:
    assert page, 'an empty page was yielded'


def test_candles_can_be_fetched(window_result: CandlesResult):
  """Fetch three days of hourly candles without an implementation or transport error."""
  if window_result.failure is not None:
    pytest.fail(window_result.failure, pytrace=False)


def test_candles_are_unique_aligned_and_bounded(window_result: CandlesResult):
  """Opens respect the contract; empty venue slots and native ordering are allowed."""
  if window_result.failure is not None:
    pytest.skip('Fetch test failed for this market')
  check_series(window_result, count=WINDOW)


def test_candle_values_are_decimals_and_ordered(window_result: CandlesResult):
  """Every price is a `Decimal` and `low <= open, close <= high` on every candle."""
  if window_result.failure is not None:
    pytest.skip('Fetch test failed for this market')
  for candle in window_result.candles:
    for value in (candle.open, candle.high, candle.low, candle.close):
      assert isinstance(value, Decimal)
    assert candle.low <= candle.open <= candle.high
    assert candle.low <= candle.close <= candle.high
    assert candle.volume is None or isinstance(candle.volume, Decimal)
    assert candle.quote_volume is None or isinstance(candle.quote_volume, Decimal)


def test_window_straddling_two_pages_respects_contract(
  straddle_result: CandlesResult, candle_case: CandleCase
):
  """A reference window crosses pages without duplicates or out-of-range opens."""
  if straddle_result.failure is not None:
    pytest.fail(straddle_result.failure, pytrace=False)
  assert len(straddle_result.pages or []) >= 2, 'the window did not straddle two pages'
  assert candle_case.page is not None
  check_series(straddle_result, count=candle_case.page + STRADDLE_EXTRA)
