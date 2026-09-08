"""A failed candle page retries in place without replaying earlier pages."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from typed_core.exceptions import RateLimited as TypedRateLimited
from typed_mexc.spot.http.market.candles import Candles, Response

from tribulnation.mexc.market.impl.mixin import Shared
from tribulnation.mexc.market.spot_market import SpotMarket
from tribulnation.sdk.core import Context, RateLimited


async def test_rate_limited_second_page_retries_in_place(
  monkeypatch: pytest.MonkeyPatch,
):
  """The real typed pager resumes at its boundary after a transient 429."""
  start = datetime(2026, 1, 1, tzinfo=timezone.utc)

  def row(index: int):
    """Build one already-validated typed-client response row."""
    time = start + timedelta(minutes=index)
    return (time, '1', '1', '1', '1', '2', time, '2')

  first: Response = [row(index) for index in range(500)]
  second: Response = [row(499), row(500)]
  request = AsyncMock(side_effect=[first, TypedRateLimited(429, 'throttled'), second])
  monkeypatch.setattr(Candles, 'candles', request)
  market = SpotMarket(
    shared=Shared.public(),
    meta={
      'info': {
        'symbol': 'BTCUSDT',
        'status': '1',
        'baseAsset': 'BTC',
        'quoteAsset': 'USDT',
        'quotePrecision': 8,
        'makerCommission': Decimal(0),
        'takerCommission': Decimal(0),
        'orderTypes': [],
        'isSpotTradingAllowed': True,
        'isMarginTradingAllowed': False,
        'baseAssetPrecision': 8,
        'fullName': 'Bitcoin',
        'permissions': ['SPOT'],
        'quoteAssetPrecision': 8,
        'tradeSideType': 1,
      }
    },
  )
  with Context().retried(RateLimited, max_retries=1, base_delay=0).use():
    pages = [page async for page in market.candles('1m', start)]

  assert [len(page) for page in pages] == [500, 1]
  assert [c.time for page in pages for c in page] == [
    row(index)[0] for index in range(501)
  ]
  assert [call.kwargs['start_time'] for call in request.await_args_list] == [
    start,
    row(499)[0],
    row(499)[0],
  ]
