"""Kraken's retained candle window obeys SDK bounds and keeps typed row values."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from typed_core.validation import validator
from typed_kraken.spot.market_data.ohlc import Ohlc, OhlcResult

from tribulnation.kraken.market.impl.mixin import Shared
from tribulnation.kraken.market.spot_market import SpotMarket

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


def response(indices: list[int]) -> OhlcResult:
  """Validate a wire-shaped fixture through the same type used by the endpoint."""
  return validator(OhlcResult).python(
    {
      'XXBTZUSD': [
        [int((START + index * MINUTE).timestamp()), '1', '3', '1', '2', '2', '4', 5]
        for index in indices
      ],
      'last': int(START.timestamp()),
    }
  )


@pytest.fixture
def market():
  """Construct a public market without fetching the catalogue."""
  return SpotMarket(
    shared=Shared.new(public=True),
    meta={
      'pair': {'key': 'XXBTZUSD', 'symbol': 'BTC/USD', 'info': {'altname': 'XBTUSD'}}
    },
  )


async def test_candles_keep_native_order_and_half_open_bounds(
  market: SpotMarket,
  monkeypatch: pytest.MonkeyPatch,
):
  """The exclusive end and duplicate opens are removed without sorting the response."""
  request = AsyncMock(return_value=response([3, 2, 0, 2, -1]))
  monkeypatch.setattr(Ohlc, 'ohlc', request)
  rows = await market.candles('1m', START, START + 3 * MINUTE)
  assert [row.time for row in rows] == [START + 2 * MINUTE, START]
  assert rows[0].volume == 4 and rows[0].trades == 5
  assert request.await_args is not None
  assert request.await_args.kwargs['since'] == START - MINUTE


async def test_old_range_returns_no_rows_and_does_not_fake_pagination(
  market: SpotMarket,
  monkeypatch: pytest.MonkeyPatch,
):
  """A newer retained page cannot be advanced into history the venue no longer serves."""
  request = AsyncMock(return_value=response([1000, 1001]))
  monkeypatch.setattr(Ohlc, 'ohlc', request)
  assert await market.candles('1m', START, START + MINUTE) == []
  request.assert_awaited_once()


async def test_empty_range_needs_no_request(
  market: SpotMarket, monkeypatch: pytest.MonkeyPatch
):
  """Equal bounds are empty before reaching the venue."""
  request = AsyncMock()
  monkeypatch.setattr(Ohlc, 'ohlc', request)
  assert await market.candles('1m', START, START) == []
  request.assert_not_awaited()


def test_invalid_bounds_fail_before_request(market: SpotMarket):
  """The shared candle contract validates awareness and bound ordering."""
  with pytest.raises(ValueError, match='timezone-aware'):
    market.candles('1m', START.replace(tzinfo=None), START)
  with pytest.raises(ValueError, match='precede'):
    market.candles('1m', START + MINUTE, START)
