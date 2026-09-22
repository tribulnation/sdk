"""Exchange history uses native all-market queries within one dYdX subaccount."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import Any
from unittest.mock import AsyncMock, Mock

import pytest
from typed_core import PaginatedResponse
from typed_core.exceptions import NetworkError as ClientNetworkError

from tribulnation.dydx.market.exchange import Exchange
from tribulnation.sdk import Context, NetworkError
from tribulnation.sdk.market import ExchangeFundingPayment, ExchangeTrade


@pytest.mark.parametrize('subaccount', [0, 128])
@pytest.mark.parametrize('kind', ['trades', 'funding'])
async def test_exchange_history_scope_bounds_retry(
  monkeypatch: pytest.MonkeyPatch, subaccount: int, kind: str
):
  """Keep mixed tickers and inclusive bounds while retrying only a failed page."""
  start = datetime(2026, 1, 1, tzinfo=timezone.utc)
  end = start + timedelta(hours=1)
  calls: list[int] = []

  async def fetch(state: int) -> tuple[list[dict[str, Any]], int | None]:
    """Include an out-of-range page and fail its first request."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientNetworkError('disconnected')
    time = [start, end + timedelta(seconds=1), end][state]
    ticker = ['BTC-USD', 'BTC-USD', 'DELISTED-USD'][state]
    row: dict[str, Any] = (
      {
        'id': str(state),
        'market': ticker,
        'side': 'SELL',
        'price': '10',
        'size': '2',
        'createdAt': time,
        'liquidity': 'MAKER',
        'fee': '0.1',
      }
      if kind == 'trades'
      else {'ticker': ticker, 'payment': '-0.5', 'createdAt': time}
    )
    return [row], state + 1 if state < 2 else None

  exchange = Exchange.new(address='dydx1fixture')
  exchange = Exchange(shared=exchange.shared, subaccount=subaccount)
  endpoint = 'get_fills_paged' if kind == 'trades' else 'get_funding_payments_paged'
  paging = Mock(return_value=PaginatedResponse(0, fetch))
  markets = AsyncMock(side_effect=AssertionError('Must not enumerate markets'))
  subaccounts = AsyncMock(side_effect=AssertionError('Must not enumerate accounts'))
  monkeypatch.setattr(type(exchange.indexer.data), endpoint, paging)
  monkeypatch.setattr(type(exchange.indexer.data), 'get_markets', markets)
  monkeypatch.setattr(type(exchange.indexer.data), 'get_subaccounts', subaccounts)
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    response = (
      exchange.trades_history(None, start, end)
      if kind == 'trades'
      else exchange.funding_payments(None, start, end)
    )
    pages = [page async for page in response]
  rows = [row for page in pages for row in page]
  assert [len(page) for page in pages] == [1, 1]
  assert [row.time for row in rows] == [start, end]
  assert all(isinstance(row, (ExchangeTrade, ExchangeFundingPayment)) for row in rows)
  market_ids: list[str] = []
  for row in rows:
    assert isinstance(row, (ExchangeTrade, ExchangeFundingPayment))
    market_ids.append(row.market_id)
  assert market_ids == ['BTC-USD', 'DELISTED-USD']
  if kind == 'trades':
    assert all(
      isinstance(row, ExchangeTrade) and row.qty == Decimal('-2') for row in rows
    )
  else:
    assert all(
      isinstance(row, ExchangeFundingPayment) and row.amount == Decimal('0.5')
      for row in rows
    )
  expected: dict[str, object] = {'address': 'dydx1fixture', 'subaccount': subaccount}
  if kind == 'trades':
    expected.update(created_before_or_at=end, market_type='PERPETUAL')
  else:
    expected.update(after_or_at=start)
  paging.assert_called_once_with(**expected)
  assert calls == [0, 1, 1, 2]
  markets.assert_not_called()
  subaccounts.assert_not_called()


@pytest.mark.parametrize('method', ['trades_history', 'funding_payments'])
async def test_selected_market_history_delegates(
  monkeypatch: pytest.MonkeyPatch, method: str
):
  """Existing market selections retain their delegated records and arguments."""
  start = datetime(2026, 1, 1, tzinfo=timezone.utc)
  rows = [object()]

  async def fetch(state: int):
    """Return a single existing market page."""
    return rows, None

  history = Mock(return_value=PaginatedResponse(0, fetch))
  market = Mock(**{method: history})
  lookup = AsyncMock(return_value=market)
  monkeypatch.setattr(Exchange, 'market', lookup)
  exchange = Exchange.new(address='dydx1fixture')
  assert await getattr(exchange, method)('BTC-USD', start, start) == rows
  lookup.assert_awaited_once_with('BTC-USD')
  history.assert_called_once_with(start, start)


async def test_market_funding_payment_sign(monkeypatch: pytest.MonkeyPatch):
  """Selected market history also reports received funding as negative."""
  from tribulnation.dydx.market.impl.funding import funding_payments
  from tribulnation.dydx.market.impl.mixin import MarketMixin

  start = datetime(2026, 1, 1, tzinfo=timezone.utc)

  async def fetch(state: int) -> tuple[list[dict[str, Any]], None]:
    """Return one native payment received by the account."""
    return [{'payment': Decimal('2'), 'createdAt': start}], None

  exchange = Exchange.new(address='dydx1fixture')
  monkeypatch.setattr(
    type(exchange.indexer.data),
    'get_subaccounts',
    AsyncMock(return_value={'subaccounts': [{'subaccountNumber': 0}]}),
  )
  monkeypatch.setattr(
    type(exchange.indexer.data),
    'get_funding_payments_paged',
    Mock(return_value=PaginatedResponse(0, fetch)),
  )
  monkeypatch.setattr(MarketMixin, 'market', 'BTC-USD')
  market = MarketMixin(shared=exchange.shared, perpetual_market=Mock())
  rows = [row async for page in funding_payments(market, start, start) for row in page]
  assert [row.amount for row in rows] == [Decimal('-2')]


@pytest.mark.parametrize('subaccount', [0, 128])
@pytest.mark.parametrize('method', ['trades_history', 'funding_payments'])
async def test_selected_market_history_subaccount(
  monkeypatch: pytest.MonkeyPatch, subaccount: int, method: str
):
  """A selected market reads only its exchange bucket, excluding sibling accounts."""
  from tribulnation.dydx.market.impl.mixin import Shared

  start = datetime(2026, 1, 1, tzinfo=timezone.utc)

  async def fetch(state: int) -> tuple[list[dict[str, Any]], None]:
    """Supply one selected-market trade or funding receipt."""
    return [
      {
        'id': 'fill',
        'market': 'BTC-USD',
        'side': 'BUY',
        'price': '1',
        'size': '1',
        'createdAt': start,
        'liquidity': 'MAKER',
        'fee': '0',
        'payment': '2',
      }
    ], None

  owner = Exchange.new(address='dydx1fixture')
  exchange = Exchange(shared=owner.shared, subaccount=subaccount)
  monkeypatch.setattr(
    Shared,
    'load_markets',
    AsyncMock(return_value={'BTC-USD': {'ticker': 'BTC-USD'}}),
  )
  accounts = AsyncMock(
    return_value={'subaccounts': [{'subaccountNumber': 0}, {'subaccountNumber': 128}]}
  )
  monkeypatch.setattr(type(exchange.indexer.data), 'get_subaccounts', accounts)
  endpoint = (
    'get_fills_paged' if method == 'trades_history' else 'get_funding_payments_paged'
  )
  paging = Mock(return_value=PaginatedResponse(0, fetch))
  monkeypatch.setattr(type(exchange.indexer.data), endpoint, paging)
  rows = await getattr(exchange, method)('BTC-USD', start, start)
  assert len(rows) == 1
  expected: dict[str, object] = {'address': 'dydx1fixture', 'subaccount': subaccount}
  if method == 'trades_history':
    expected.update(
      market='BTC-USD', market_type='PERPETUAL', created_before_or_at=start
    )
  else:
    expected.update(ticker='BTC-USD', after_or_at=start)
    assert rows[0].amount == Decimal('-2')
  paging.assert_called_once_with(**expected)
  accounts.assert_not_called()
