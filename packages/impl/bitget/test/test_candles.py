"""Bitget candle windows obey SDK bounds without sorting or buffering history."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_bitget import Bitget
from typed_bitget.classic.mix.market.candles.history import History
from typed_bitget.classic.spot.candles import Candles
from typed_bitget.schemas import MixCandle

from tribulnation.bitget.market import PerpMarket, SpotMarket
from tribulnation.bitget.core import SdkMixin
from tribulnation.bitget.market.impl.candles import SpotCandle

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


@dataclass
class Harness:
  """A real market and typed pager with only its HTTP endpoint replaced."""

  market: SpotMarket | PerpMarket
  request: AsyncMock
  window: int
  spot: bool

  def row(self, index: int) -> SpotCandle | MixCandle:
    """Build one parsed venue row at a known opening time."""
    values: MixCandle = (
      START + index * MINUTE,
      Decimal(1),
      Decimal(2),
      Decimal(1),
      Decimal(2),
      Decimal(3),
      Decimal(4),
    )
    return (*values, Decimal(5)) if self.spot else values


@pytest.fixture(params=['spot', 'usdt', 'usdc', 'coin-classic'])
def harness(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
  """Exercise both endpoint families through their generated pagination."""
  endpoint = AsyncMock()
  account = SdkMixin(client=Bitget.new(public=True))
  if request.param == 'spot':
    monkeypatch.setattr(Candles, 'candles', endpoint)
    return Harness(SpotMarket(account=account, symbol='BTCUSDT'), endpoint, 999, True)
  monkeypatch.setattr(History, 'history', endpoint)
  from tribulnation.bitget.market.impl.parse import PERP_PRODUCTS

  product = PERP_PRODUCTS[request.param]
  symbol = {'usdt': 'BTCUSDT', 'usdc': 'BTCPERP', 'coin-classic': 'BTCUSD'}[request.param]
  return Harness(
    PerpMarket(account=account, symbol=symbol, perp_product=product),
    endpoint,
    198,
    False,
  )


async def test_half_open_windows_preserve_native_order(harness: Harness):
  """A shared boundary belongs to the next window and end is excluded."""
  n = harness.window
  harness.request.side_effect = [
    [harness.row(n), harness.row(n - 1), harness.row(0)],
    [harness.row(n + 2), harness.row(n + 1), harness.row(n), harness.row(n - 1)],
  ]
  pages = [
    page async for page in harness.market.candles('1m', START, START + (n + 2) * MINUTE)
  ]
  assert [[c.time for c in page] for page in pages] == [
    [START + (n - 1) * MINUTE, START],
    [START + (n + 1) * MINUTE, START + n * MINUTE],
  ]
  assert harness.request.await_count == 2
  if isinstance(harness.market, PerpMarket):
    assert all(
      call.kwargs['product_type'] == harness.market.product
      for call in harness.request.await_args_list
    )


async def test_trading_is_unimplemented_offline(harness: Harness):
  """Check the deliberate trading gap using a fixture client, never a live account."""
  with pytest.raises(NotImplementedError, match='Trading is not implemented'):
    await harness.market.place_order(
      {'type': 'LIMIT', 'qty': Decimal(1), 'price': Decimal(1)}
    )
  with pytest.raises(NotImplementedError, match='Trading is not implemented'):
    await harness.market.cancel_order('fixture-order')
  harness.request.assert_not_called()


async def test_fractional_bounds_keep_only_matching_opens(harness: Harness):
  """Wire timestamp rounding must not drop an opening before a fractional end."""
  harness.request.return_value = [harness.row(2), harness.row(1), harness.row(0)]
  start = START + timedelta(microseconds=1)
  end = START + MINUTE + timedelta(microseconds=1)
  assert [c.time for c in await harness.market.candles('1m', start, end)] == [
    START + MINUTE
  ]
  call = harness.request.await_args
  assert call is not None
  assert call.kwargs['end_time'] > end


async def test_empty_window_does_not_hide_later_data(harness: Harness):
  """An empty historical interval does not terminate the complete range."""
  n = harness.window
  harness.request.side_effect = [[], [harness.row(n)]]
  assert [
    c.time for c in await harness.market.candles('1m', START, START + (n + 1) * MINUTE)
  ] == [START + n * MINUTE]
  assert harness.request.await_count == 2


async def test_first_page_does_not_fetch_later_windows(harness: Harness):
  """Iteration streams one bounded page without reading the whole request."""
  harness.request.return_value = [harness.row(0)]
  pages = harness.market.candles('1m', START, START + 3 * harness.window * MINUTE)
  async for page in pages:
    assert [c.time for c in page] == [START]
    break
  assert harness.request.await_count == 1


async def test_empty_range_needs_no_request(harness: Harness):
  """Equal bounds produce an empty response without touching the venue."""
  assert await harness.market.candles('1m', START, START) == []
  harness.request.assert_not_awaited()


def test_invalid_bounds_fail_before_request(harness: Harness):
  """Both required bounds must be aware and ordered."""
  with pytest.raises(ValueError, match='timezone-aware'):
    harness.market.candles('1m', START.replace(tzinfo=None), START)
  with pytest.raises(ValueError, match='precede'):
    harness.market.candles('1m', START + MINUTE, START)
  harness.request.assert_not_awaited()


async def test_full_perp_window_does_not_walk_before_start(
  monkeypatch: pytest.MonkeyPatch,
):
  """Two wire-boundary rows can fill the cap without requiring another request."""
  harness = Harness(
    PerpMarket(account=SdkMixin(client=Bitget.new(public=True)), symbol='BTCUSDT'),
    AsyncMock(),
    198,
    False,
  )
  harness.request.side_effect = [
    [harness.row(index) for index in range(-1, 199)],
    AssertionError('A complete bounded window must not page backwards'),
  ]
  monkeypatch.setattr(History, 'history', harness.request)
  rows = await harness.market.candles('1m', START, START + 198 * MINUTE)
  assert [c.time for c in rows] == [START + i * MINUTE for i in range(198)]
  harness.request.assert_awaited_once()
