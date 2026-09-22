"""Exchange-wide history is explicit and preserves existing market delegation."""

from typing_extensions import AsyncIterable
from datetime import datetime, timezone
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.market import (
  Exchange,
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  PerpExchange,
  Trade,
)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 2, tzinfo=timezone.utc)


@pytest.mark.parametrize(
  'owner,method',
  [(Exchange, 'trades_history'), (PerpExchange, 'funding_payments')],
)
async def test_unsupported_exchange_history_does_not_scan_markets(
  owner: type[Exchange], method: str
):
  """A current catalogue cannot establish complete account history."""
  exchange = SimpleNamespace(id='test:perp', market=AsyncMock(), markets=AsyncMock())
  with pytest.raises(NotImplementedError, match='Exchange-wide'):
    await getattr(owner, method)(exchange, None, START, END)
  exchange.market.assert_not_awaited()
  exchange.markets.assert_not_awaited()


@pytest.mark.parametrize(
  'owner,method',
  [(Exchange, 'trades_history'), (PerpExchange, 'funding_payments')],
)
async def test_selected_market_preserves_pages(owner: type[Exchange], method: str):
  """Existing selected-market calls retain records, empty pages and window bounds."""
  row = (
    Trade(id='fill', price=Decimal('2'), qty=Decimal('1'), time=START, maker=False)
    if method == 'trades_history'
    else FundingPayment(amount=Decimal('2'), time=START)
  )
  pages: list[list[Trade | FundingPayment]] = [[row], [], [row]]

  async def stream() -> AsyncIterable[list[Trade | FundingPayment]]:
    """Supply fixture pages including an empty page."""
    for page in pages:
      yield page

  history = Mock(return_value=PaginatedResponse(stream()))
  market = SimpleNamespace(**{method: history})
  exchange = SimpleNamespace(market=AsyncMock(return_value=market))
  result = [page async for page in getattr(owner, method)(exchange, 'BTC', START, END)]
  assert result == pages
  assert result[0][0] is row
  exchange.market.assert_awaited_once_with('BTC')
  history.assert_called_once_with(START, END)


def test_exchange_records_preserve_base_shape_and_native_identity():
  """An exchange row retains the base API and a required unqualified market ID."""
  trade = ExchangeTrade(
    market_id='xyz:ABC',
    id='123',
    price=Decimal('2'),
    qty=Decimal('-1'),
    time=START,
    maker=False,
  )
  payment = ExchangeFundingPayment(market_id='xyz:ABC', amount=Decimal('1'), time=START)
  assert isinstance(trade, Trade)
  assert isinstance(payment, FundingPayment)
  assert trade.market_id == payment.market_id == 'xyz:ABC'
  with pytest.raises(TypeError):
    ExchangeFundingPayment(amount=Decimal('1'), time=START)  # type: ignore[call-arg]


@pytest.mark.parametrize(
  'module,class_name',
  [
    (f'tribulnation.{venue}.market.{kind}_exchange', f'{kind.title()}Exchange')
    for venue in ('binance', 'bitget', 'bybit', 'coinbase', 'kraken', 'mexc')
    for kind in ('spot', 'perp')
  ]
  + [('tribulnation.bit2me.market.spot_exchange', 'SpotExchange')]
  + [
    (f'tribulnation.{venue}.market.exchanges', class_name)
    for venue in ('deribit', 'kucoin')
    for class_name in ('SpotExchange', 'LinearPerpExchange')
  ],
)
async def test_other_venues_reject_exchange_wide_history(module: str, class_name: str):
  """Every non-HL/dYdX exchange rejects all-market reads before accessing a client."""
  owner: type[Exchange] = getattr(import_module(module), class_name)
  exchange = SimpleNamespace(
    id='test:exchange', market=AsyncMock(), markets=AsyncMock()
  )
  methods = ['trades_history']
  if issubclass(owner, PerpExchange):
    methods.append('funding_payments')
  for method in methods:
    with pytest.raises(NotImplementedError, match='Exchange-wide'):
      await getattr(owner, method)(exchange, None, START, END)
  exchange.market.assert_not_awaited()
  exchange.markets.assert_not_awaited()
