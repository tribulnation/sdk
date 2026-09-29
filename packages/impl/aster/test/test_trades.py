"""Perpetual trade history: seven-day windows, inclusive bounds, retries and rows."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import Any, Literal
import pytest
from typed_core import NetworkError as ClientNetworkError
from typed_aster.futures.trade.user_trades import UserTrades
from tribulnation.aster import AsterMarket
from tribulnation.aster.market import markets
from tribulnation.aster.market.markets import PerpMarket, parse_trade
from tribulnation.sdk import Context, NetworkError
from tribulnation.sdk.core import MissingData
from tribulnation.sdk.market import Trade

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
MS = timedelta(milliseconds=1)


def trade(id: int, time: datetime, side: Literal['BUY', 'SELL'] = 'BUY') -> Any:
  """One native perpetual fill."""
  return {
    'id': id,
    'orderId': id,
    'symbol': 'BTCUSDT',
    'side': side,
    'price': Decimal(100),
    'qty': Decimal(2),
    'time': time,
    'maker': id % 2 == 0,
    'commission': Decimal('0.1'),
    'commissionAsset': 'USDT',
  }


def market() -> PerpMarket:
  """A perpetual market over a credential-free client; requests are mocked."""
  return PerpMarket(shared=AsterMarket.new(public=True).shared, symbol='BTCUSDT')


@pytest.mark.parametrize('collect', [False, True])
async def test_windows_are_walked_by_id_and_pages_retried_alone(
  collect: bool, monkeypatch: pytest.MonkeyPatch
):
  """A retried page repeats no rows, and a row on a window edge is read once."""
  end = START + timedelta(days=10)
  split = START + markets.TRADES_WINDOW
  rows = [
    trade(1, START),
    trade(2, START + timedelta(days=1), 'SELL'),
    trade(3, split),
    trade(4, end),
  ]
  endpoint = AsyncMock(
    side_effect=[
      rows[0:2],
      ClientNetworkError('offline'),
      rows[1:3],
      rows[2:3],
      rows[3:4],
    ]
  )
  monkeypatch.setattr(UserTrades, 'user_trades', endpoint)
  monkeypatch.setattr(markets, 'TRADES_PAGE', 2)
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    request = market().trades_history(START, end)
    result = await request if collect else [t async for page in request for t in page]
  assert [(t.id, t.qty) for t in result] == [('1', 2), ('2', -2), ('3', 2), ('4', 2)]
  assert [
    (c.kwargs['start_time'], c.kwargs['end_time'], c.kwargs['from_id'])
    for c in endpoint.await_args_list
  ] == [
    (START, split, None),
    (None, None, 2),
    (None, None, 2),
    (None, None, 3),
    (split + MS, end, None),
  ]


async def test_no_window_starts_or_ends_in_the_future(monkeypatch: pytest.MonkeyPatch):
  """The venue refuses future bounds, so the walk stops at the current time."""
  endpoint = AsyncMock(return_value=[])
  monkeypatch.setattr(UserTrades, 'user_trades', endpoint)
  now = datetime.now(timezone.utc)
  assert (
    await market().trades_history(now - timedelta(days=1), now + timedelta(days=30))
    == []
  )
  (call,) = endpoint.await_args_list
  assert call.kwargs['start_time'] == now - timedelta(days=1)
  assert now <= call.kwargs['end_time'] <= datetime.now(timezone.utc)
  assert (
    await market().trades_history(now + timedelta(days=1), now + timedelta(days=2))
    == []
  )
  assert endpoint.await_count == 1
  with pytest.raises(ValueError, match='timezone-aware'):
    market().trades_history(START.replace(tzinfo=None), START)


async def test_rows_outside_submillisecond_bounds_are_dropped(
  monkeypatch: pytest.MonkeyPatch,
):
  """The venue floors bounds to milliseconds; the caller's own bounds still hold."""
  start, end = START + MS / 2, START + timedelta(minutes=1) + MS / 2
  endpoint = AsyncMock(
    return_value=[trade(1, START), trade(2, START + timedelta(minutes=1))]
  )
  monkeypatch.setattr(UserTrades, 'user_trades', endpoint)
  assert [t.id for t in await market().trades_history(start, end)] == ['2']


def test_trade_rows_map_signed_quantities_and_fees():
  """A fee needs both native fields; side and maker are never guessed."""
  row = trade(2, START, 'SELL')
  assert parse_trade(row) == Trade(
    id='2',
    order_id='2',
    price=Decimal(100),
    qty=Decimal(-2),
    time=START,
    maker=True,
    fee=Trade.Fee(amount=Decimal('0.1'), asset='USDT'),
    details=row,
  )
  unpriced = trade(1, START)
  del unpriced['commission'], unpriced['commissionAsset']
  assert parse_trade(unpriced).fee is None
  partial = trade(1, START)
  del partial['commissionAsset']
  with pytest.raises(MissingData, match='commission'):
    parse_trade(partial)
  sideless = trade(1, START)
  del sideless['side']
  with pytest.raises(MissingData, match='side'):
    parse_trade(sideless)
