"""Public funding history honors the SDK's earliest-available default."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from typed_binance.usdm_futures.http.market.funding_rate import FundingRate
from tribulnation.binance import BinanceMarket


@pytest.mark.parametrize(
  'start',
  [
    None,
    datetime(1970, 1, 1, tzinfo=timezone.utc),
    datetime(1900, 1, 1, tzinfo=timezone.utc),
  ],
)
async def test_omitted_start_requests_earliest_not_recent(
  monkeypatch: pytest.MonkeyPatch,
  start: datetime | None,
):
  """Binance's default latest slice must not silently truncate an unbounded walk."""
  request = AsyncMock(return_value=[])
  monkeypatch.setattr(FundingRate, 'funding_rate', request)
  async with BinanceMarket.new(public=True) as sdk:
    market = await (await sdk.perp_exchange('usdm')).market('BTCUSDT')
    assert await market.funding_rates(start) == []
  request.assert_awaited_once_with(
    'BTCUSDT',
    start_time=datetime(1970, 1, 1, microsecond=1000, tzinfo=timezone.utc),
    end_time=None,
    limit=1000,
    validate=None,
  )


async def test_history_before_epoch_is_empty(monkeypatch: pytest.MonkeyPatch):
  """A pre-exchange interval must not become an unbounded recent-history request."""
  request = AsyncMock(return_value=[])
  monkeypatch.setattr(FundingRate, 'funding_rate', request)
  async with BinanceMarket.new(public=True) as sdk:
    market = await (await sdk.perp_exchange('usdm')).market('BTCUSDT')
    assert (
      await market.funding_rates(end=datetime(1970, 1, 1, tzinfo=timezone.utc)) == []
    )
  request.assert_not_awaited()


async def test_explicit_bounds_are_preserved(monkeypatch: pytest.MonkeyPatch):
  """User-specified inclusive history windows reach the typed pager unchanged."""
  request = AsyncMock(return_value=[])
  monkeypatch.setattr(FundingRate, 'funding_rate', request)
  start = datetime(2026, 1, 1, tzinfo=timezone.utc)
  end = datetime(2026, 1, 2, tzinfo=timezone.utc)
  async with BinanceMarket.new(public=True) as sdk:
    market = await (await sdk.perp_exchange('usdm')).market('BTCUSDT')
    assert await market.funding_rates(start, end) == []
  request.assert_awaited_once_with(
    'BTCUSDT',
    start_time=start,
    end_time=end,
    limit=1000,
    validate=None,
  )
