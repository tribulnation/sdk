"""Live conformance tests for `Market.candles` implementations."""

from decimal import Decimal

import pytest

from .support import HOUR, START, STRADDLE_EXTRA, WINDOW, CandleCase, CandlesResult


def check_series(result: CandlesResult, *, count: int):
  """Assert the contract over a fetched series: exact count, ascending, aligned."""
  candles = result.candles
  assert len(candles) == count, f'expected {count} candles, got {len(candles)}'
  expected = [START + k * HOUR for k in range(count)]
  assert [c.time for c in candles] == expected, 'candles are not hourly-aligned'
  for page in result.pages or []:
    assert page, 'an empty page was yielded'
  for previous, page in zip(result.pages or [], (result.pages or [])[1:]):
    assert previous[-1].time < page[0].time, 'pages overlap or are out of order'


def test_candles_can_be_fetched(window_result: CandlesResult):
  """Fetch three days of hourly candles without an implementation or transport error."""
  if window_result.failure is not None:
    pytest.fail(window_result.failure, pytrace=False)


def test_candles_are_ascending_aligned_and_complete(window_result: CandlesResult):
  """Three days come back as 72 consecutive hourly candles, oldest first."""
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


def test_window_straddling_two_pages_is_exact(
  straddle_result: CandlesResult, candle_case: CandleCase
):
  """A window one page plus fifty candles wide yields at least two pages and every
  candle exactly once."""
  if straddle_result.failure is not None:
    pytest.fail(straddle_result.failure, pytrace=False)
  assert len(straddle_result.pages or []) >= 2, 'the window did not straddle two pages'
  check_series(straddle_result, count=candle_case.page + STRADDLE_EXTRA)
