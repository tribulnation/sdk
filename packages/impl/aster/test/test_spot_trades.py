"""Spot trade history: per-fill fee assets, windows, halving and page retries.

Fill fixtures follow the shape of mainnet USDCUSDT fills read on 2026-10-08 (a taker
buy paying USDC, a taker sell paying USDT), with invented IDs, prices and sizes.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import Any, Literal

import pytest
from typed_core import NetworkError as ClientNetworkError
from typed_aster.spot.trade.user_trades import UserTrades
from tribulnation.aster import AsterMarket
from tribulnation.aster.core import Shared
from tribulnation.aster.market import markets
from tribulnation.aster.market.markets import SpotMarket, parse_trade
from tribulnation.sdk import Context, NetworkError
from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import ExchangeTrade, Trade

START = datetime(2026, 9, 1, tzinfo=timezone.utc)
MS = timedelta(milliseconds=1)


def fill(
  id: int, time: datetime, side: Literal['BUY', 'SELL'], symbol: str = 'USDCUSDT'
) -> Any:
  """One native spot fill; the fee is paid in the asset the fill delivers."""
  base = symbol.removesuffix('USDT')
  return {
    'symbol': symbol,
    'id': id,
    'orderId': id + 1000,
    'side': side,
    'price': Decimal('0.9998'),
    'qty': Decimal(10),
    'quoteQty': Decimal('9.998'),
    'commission': Decimal('0.004') if side == 'BUY' else Decimal('0.0039992'),
    'commissionAsset': base if side == 'BUY' else 'USDT',
    'time': time,
    'counterpartyId': 1,
    'createUpdateId': None,
    'maker': False,
    'buyer': side == 'BUY',
  }


def test_spot_fills_keep_their_own_fee_asset():
  """Buys pay in the base asset and sells in the quote, so rules name neither."""
  buy, sell = fill(1, START, 'BUY'), fill(2, START, 'SELL')
  assert parse_trade(buy) == Trade(
    id='1',
    order_id='1001',
    price=Decimal('0.9998'),
    qty=Decimal(10),
    time=START,
    maker=False,
    fee=Trade.Fee(amount=Decimal('0.004'), asset='USDC'),
    details=buy,
  )
  mapped = parse_trade(sell)
  assert mapped.qty == -10 and mapped.fee == Trade.Fee(
    amount=Decimal('0.0039992'), asset='USDT'
  )


def venue() -> AsterMarket:
  """A mainnet venue over a credential-free client; requests are mocked."""
  return AsterMarket.new(public=True)


@pytest.mark.parametrize('collect', [False, True])
async def test_pair_history_walks_windows_and_retries_pages(
  collect: bool, monkeypatch: pytest.MonkeyPatch
):
  """Seven-day windows by `fromId`; a retried page repeats no rows."""
  end = START + timedelta(days=10)
  split = START + markets.TRADES_WINDOW
  rows = [
    fill(1, START, 'BUY'),
    fill(2, START + timedelta(days=1), 'SELL'),
    fill(3, split, 'BUY'),
    fill(4, end, 'SELL'),
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
  market = SpotMarket(shared=venue().shared, symbol='USDCUSDT')
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    request = market.trades_history(START, end)
    result = await request if collect else [t async for page in request for t in page]
  assert [(t.id, t.qty, t.fee and t.fee.asset) for t in result] == [
    ('1', 10, 'USDC'),
    ('2', -10, 'USDT'),
    ('3', 10, 'USDC'),
    ('4', -10, 'USDT'),
  ]
  assert [
    (c.args[0], c.kwargs['start_time'], c.kwargs['end_time'], c.kwargs['from_id'])
    for c in endpoint.await_args_list
  ] == [
    ('USDCUSDT', START, split, None),
    ('USDCUSDT', None, None, 2),
    ('USDCUSDT', None, None, 2),
    ('USDCUSDT', None, None, 3),
    ('USDCUSDT', split + MS, end, None),
  ]


@pytest.mark.parametrize('collect', [False, True])
async def test_exchange_history_halves_full_windows_and_retries_alone(
  collect: bool, monkeypatch: pytest.MonkeyPatch
):
  """A full symbol-less page is split in two; each half is retried on its own."""
  end = START + timedelta(days=1)
  middle = START + timedelta(hours=12)
  first = [fill(1, START, 'BUY'), fill(7, middle, 'SELL', 'ASTERUSDT')]
  endpoint = AsyncMock(
    side_effect=[
      first + [fill(2, end, 'SELL')],
      ClientNetworkError('offline'),
      first,
      [fill(2, end, 'SELL')],
    ]
  )
  monkeypatch.setattr(UserTrades, 'user_trades', endpoint)
  monkeypatch.setattr(markets, 'TRADES_PAGE', 3)
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    request = venue().spot.trades_history(None, START, end)
    result = await request if collect else [t async for page in request for t in page]
  assert all(isinstance(t, ExchangeTrade) for t in result)
  assert [(t.market_id, t.id) for t in result if isinstance(t, ExchangeTrade)] == [
    ('USDCUSDT', '1'),
    ('ASTERUSDT', '7'),
    ('USDCUSDT', '2'),
  ]
  assert [
    (c.kwargs['start_time'], c.kwargs['end_time']) for c in endpoint.await_args_list
  ] == [(START, end), (START, middle), (START, middle), (middle + MS, end)]
  assert all('symbol' not in c.kwargs and not c.args for c in endpoint.await_args_list)


async def test_exchange_history_rejects_an_unsplittable_page(
  monkeypatch: pytest.MonkeyPatch,
):
  """A full page within one millisecond cannot be split; rows are never dropped."""
  monkeypatch.setattr(
    UserTrades, 'user_trades', AsyncMock(return_value=[fill(1, START, 'BUY')])
  )
  monkeypatch.setattr(markets, 'TRADES_PAGE', 1)
  with pytest.raises(ApiError, match='one millisecond'):
    await venue().spot.trades_history(None, START, START)


async def test_exchange_history_delegates_one_pair(monkeypatch: pytest.MonkeyPatch):
  """A market ID reads that pair's own history through the pair's pager."""
  endpoint = AsyncMock(return_value=[fill(1, START, 'BUY')])
  monkeypatch.setattr(UserTrades, 'user_trades', endpoint)
  monkeypatch.setattr(Shared, 'spot_symbols', AsyncMock(return_value={'USDCUSDT': {}}))
  result = await venue().spot.trades_history('USDCUSDT', START, START + MS)
  assert [t.id for t in result] == ['1']
  assert endpoint.await_args is not None and endpoint.await_args.args == ('USDCUSDT',)
