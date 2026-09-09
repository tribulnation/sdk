"""Native Hyperliquid candle pages use request-level retries and half-open bounds."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import cast
from unittest.mock import AsyncMock

import pytest
from typed_hyperliquid import Hyperliquid
from typed_hyperliquid.info.candle_snapshot import Candle, CandleSnapshot

from tribulnation.hyperliquid.market.impl.candles import candles
from tribulnation.hyperliquid.market.impl.mixin import (
  Shared,
  SharedMixin,
  SpotMarketMixin,
)
from tribulnation.sdk.core import Context, RateLimited

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


def row(index: int) -> Candle:
  """Build a validated candle using the venue's field names."""
  return {
    't': START + index * MINUTE,
    'T': START + (index + 1) * MINUTE,
    's': '@1',
    'i': '1m',
    'o': Decimal(1),
    'h': Decimal(2),
    'l': Decimal(1),
    'c': Decimal(2),
    'v': Decimal(3),
    'n': 4,
  }


async def test_page_retry_does_not_replay_and_end_is_exclusive(
  monkeypatch: pytest.MonkeyPatch,
):
  """A second-page failure resumes in place; an end-boundary candle is excluded."""
  request = AsyncMock(
    side_effect=[
      [row(i) for i in range(5000)],
      RateLimited(429, 'throttled'),
      [row(4999), row(5000), row(5001)],
    ]
  )
  monkeypatch.setattr(CandleSnapshot, 'candle_snapshot', request)
  client = Hyperliquid.new(public=True)
  owner = SharedMixin(shared=Shared(client=client, maybe_address=None))
  market = cast(
    SpotMarketMixin,
    SimpleNamespace(
      client=client,
      asset_name='@1',
      call_hyperliquid=owner.call_hyperliquid,
    ),
  )
  with Context().retried(RateLimited, max_retries=1, base_delay=0).use():
    pages = [page async for page in candles(market, '1m', START, START + 5001 * MINUTE)]
  assert [len(page) for page in pages] == [5000, 1]
  assert [c.time for page in pages for c in page] == [row(i)['t'] for i in range(5001)]
  assert [call.kwargs['start_time'] for call in request.await_args_list] == [
    START,
    row(4999)['t'],
    row(4999)['t'],
  ]


async def test_empty_range_makes_no_request():
  """Equal bounds return without accessing the client."""
  market = cast(SpotMarketMixin, SimpleNamespace())
  assert [page async for page in candles(market, '1m', START, START)] == []
