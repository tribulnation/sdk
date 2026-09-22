"""Exchange history walks account pages once and preserves market scope."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import Any
from unittest.mock import AsyncMock, Mock

import pytest
from typed_core import PaginatedResponse
from typed_core.exceptions import NetworkError as ClientNetworkError
from typed_hyperliquid import Hyperliquid

from tribulnation.hyperliquid.market.impl.mixin import Shared
from tribulnation.hyperliquid.market.perps_exchange import PerpExchange
from tribulnation.hyperliquid.market.spot_exchange import SpotExchange
from tribulnation.sdk import Context, NetworkError
from tribulnation.sdk.market import ExchangeFundingPayment, ExchangeTrade, Trade

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)


def fill(coin: str, tid: int) -> dict[str, Any]:
  """Build a native fill containing the fields used by the SDK mapper."""
  return {
    'coin': coin,
    'tid': tid,
    'px': Decimal('12'),
    'sz': Decimal('3'),
    'side': 'A',
    'time': START,
    'crossed': True,
    'fee': Decimal('0.1'),
    'feeToken': 'USDC',
  }


@pytest.mark.parametrize('exchange_id', ['spot', '', 'xyz'])
@pytest.mark.parametrize('collect', [False, True])
async def test_exchange_fills_scope_and_retry(
  monkeypatch: pytest.MonkeyPatch, exchange_id: str, collect: bool
):
  """Mixed account pages retry once and never leak another exchange's fills."""
  calls: list[int] = []
  chunks = [
    [fill('other:BTC', 0)],
    [fill('BTC', 1), fill('@1035', 2), fill('xyz:GOLD', 3)],
    [fill('DELISTED', 4), fill('PURR/USDC', 5), fill('xyz:SILVER', 6)],
  ]

  for coin in ('BTC', '@1035', 'xyz:GOLD'):
    for time in (START - timedelta(seconds=1), END + timedelta(seconds=1)):
      chunks[0].append({**fill(coin, 99), 'time': time})

  async def fetch(state: int):
    """Fail the second page once after a page containing no matching fills."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    return chunks[state], state + 1 if state < 2 else None

  monkeypatch.setattr(
    Shared,
    'load_spot_meta',
    AsyncMock(
      return_value={
        'tokens': [
          {'index': 0, 'name': 'USDC'},
          {'index': 1, 'name': 'PURR'},
          {'index': 150, 'name': 'HYPE'},
        ],
        'universe': [
          {'index': 0, 'name': 'PURR/USDC', 'tokens': [1, 0]},
          {'index': 1035, 'name': '@1035', 'tokens': [150, 0]},
        ],
      }
    ),
  )
  async with Hyperliquid.new(public=True) as client:
    endpoint = Mock(return_value=PaginatedResponse(0, fetch))
    monkeypatch.setattr(type(client.info), 'user_fills_by_time_paged', endpoint)
    shared = Shared(client=client, maybe_address='0xfixture')
    if exchange_id == 'spot':
      exchange = SpotExchange(shared=shared)
    else:
      exchange = PerpExchange(
        shared=shared,
        dex={'name': exchange_id, 'idx': 1} if exchange_id else None,
      )
    with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
      history = exchange.trades_history(None, START, END)
      rows = (
        await history if collect else [row async for page in history for row in page]
      )
  assert calls == [0, 1, 1, 2]
  endpoint.assert_called_once_with(user='0xfixture', start_time=START, end_time=END)
  assert all(isinstance(row, ExchangeTrade) for row in rows)
  expected = {
    'spot': [('2', 'HYPE/USDC:1035'), ('5', 'PURR/USDC:0')],
    '': [('1', 'BTC'), ('4', 'DELISTED')],
    'xyz': [('3', 'xyz:GOLD'), ('6', 'xyz:SILVER')],
  }
  assert [(row.id, row.market_id) for row in rows] == expected[exchange_id]
  assert all(
    row.qty == -3 and row.fee is not None and row.fee.asset == '0' for row in rows
  )


@pytest.mark.parametrize('dex', [None, 'xyz'])
async def test_exchange_funding_scope_and_retry(
  monkeypatch: pytest.MonkeyPatch, dex: str | None
):
  """Funding uses positive-paid signs and excludes other DEXs and times."""
  calls: list[int] = []

  async def fetch(state: int):
    """Return funding for several DEXs and one out-of-range entry."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    time = START if state == 0 else END
    rows: list[dict[str, Any]] = [
      {
        'delta': {
          'coin': coin,
          'usdc': Decimal('1.25') if state == 0 else Decimal('-2'),
        },
        'time': time,
      }
      for coin in ('BTC', 'xyz:GOLD', 'other:BTC')
    ]
    rows.append(
      {'delta': {'coin': 'BTC', 'usdc': Decimal(9)}, 'time': END + timedelta(seconds=1)}
    )
    return rows, 1 if state == 0 else None

  async with Hyperliquid.new(public=True) as client:
    endpoint = Mock(return_value=PaginatedResponse(0, fetch))
    monkeypatch.setattr(type(client.info), 'user_funding_paged', endpoint)
    exchange = PerpExchange(
      shared=Shared(client=client, maybe_address='0xfixture'),
      dex={'name': dex, 'idx': 1} if dex else None,
    )
    with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
      rows = await exchange.funding_payments(None, START, END)
  assert calls == [0, 1, 1]
  endpoint.assert_called_once_with(user='0xfixture', start_time=START, end_time=END)
  assert all(isinstance(row, ExchangeFundingPayment) for row in rows)
  assert [row.market_id for row in rows] == ['xyz:GOLD' if dex else 'BTC'] * 2
  assert [row.amount for row in rows] == [Decimal('-1.25'), Decimal('2')]
  assert [row.time for row in rows] == [START, END]


async def test_selected_market_still_delegates(monkeypatch: pytest.MonkeyPatch):
  """A selected market retains its existing record type and mapper."""
  row = Trade(id='1', price=Decimal(1), qty=Decimal(1), time=START, maker=True)

  async def fetch(state: int):
    """Return the selected market's unchanged record."""
    return [row], None

  market = Mock(trades_history=Mock(return_value=PaginatedResponse(0, fetch)))
  lookup = AsyncMock(return_value=market)
  monkeypatch.setattr(PerpExchange, 'market', lookup)
  async with Hyperliquid.new(public=True) as client:
    exchange = PerpExchange(shared=Shared(client=client), dex=None)
    assert await exchange.trades_history('BTC', START, END) == [row]
  lookup.assert_awaited_once_with('BTC')
  market.trades_history.assert_called_once_with(START, END)


async def test_unknown_historical_spot_fails(monkeypatch: pytest.MonkeyPatch):
  """Missing spot metadata raises instead of silently discarding a fill."""
  monkeypatch.setattr(
    Shared, 'load_spot_meta', AsyncMock(return_value={'tokens': [], 'universe': []})
  )

  async def fetch(state: int):
    """Return a historical spot pair absent from the current catalogue."""
    return [fill('@99', 1)], None

  async with Hyperliquid.new(public=True) as client:
    monkeypatch.setattr(
      type(client.info),
      'user_fills_by_time_paged',
      Mock(return_value=PaginatedResponse(0, fetch)),
    )
    exchange = SpotExchange(shared=Shared(client=client, maybe_address='0xfixture'))
    with pytest.raises(ValueError, match='No spot metadata'):
      await exchange.trades_history(None, START, END)
