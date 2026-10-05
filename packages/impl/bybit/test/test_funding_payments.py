"""Funding cash flows retain native signs through filtered, retried history pages."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_bybit import Bybit
from typed_core.exceptions import NetworkError as ClientNetworkError

from tribulnation.bybit.market import PerpMarket
from tribulnation.bybit.market.impl import Cache
from tribulnation.sdk import Context, NetworkError

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def test_funding_payment_cash_flow_signs(monkeypatch: pytest.MonkeyPatch):
  """Preserve income, expense and zero while excluding another market's payment."""
  rows = [
    {'symbol': 'BTCUSDT', 'funding': amount, 'transactionTime': START}
    for amount in ('2', '-3', '0')
  ]
  endpoint = AsyncMock(
    side_effect=[
      {'list': [rows[0]], 'nextPageCursor': 'next'},
      ClientNetworkError('disconnected'),
      {'list': rows[1:] + [{**rows[0], 'symbol': 'ETHUSDT'}]},
    ]
  )
  async with Bybit.new(public=True) as client:
    monkeypatch.setattr(type(client.account), 'transaction_log', endpoint)
    market = PerpMarket(client=client, cache=Cache(), symbol='BTCUSDT')
    with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
      payments = await market.funding_payments(START, START)
  assert [p.amount for p in payments] == [Decimal('2'), Decimal('-3'), Decimal('0')]
  assert [p.time for p in payments] == [START] * 3
  assert [call.kwargs['cursor'] for call in endpoint.await_args_list] == [
    None,
    'next',
    'next',
  ]
