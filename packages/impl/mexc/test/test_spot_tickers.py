"""Full MEXC spot tickers preserve quotes and native daily turnover in one read."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from tribulnation.mexc import MexcMarket


@pytest.mark.parametrize('single_response', [False, True])
async def test_full_ticker_preserves_quotes_and_native_volumes(
  monkeypatch: pytest.MonkeyPatch, single_response: bool
):
  """Do not multiply base volume by last price or make additional book requests."""
  row = {
    'symbol': 'BTCUSDT',
    'lastPrice': Decimal('100'),
    'bidPrice': Decimal('99'),
    'askPrice': Decimal('101'),
    'bidQty': Decimal('2'),
    'askQty': Decimal('3'),
    'volume': Decimal('10'),
    'quoteVolume': Decimal('987.123456789012345678'),
  }
  request = AsyncMock(return_value=row if single_response else [row])
  async with MexcMarket.public() as venue:
    monkeypatch.setattr(venue.client.spot.http.market, 'ticker_24hr', request)
    book = AsyncMock(side_effect=AssertionError('unexpected book request'))
    monkeypatch.setattr(venue.client.spot.http.market, 'book_ticker', book)
    exchange = await venue.exchange('spot')
    result = await exchange.tickers(['BTCUSDT'])
    assert set(result) == {'BTCUSDT'}
    ticker = result['BTCUSDT']
    assert (ticker.last, ticker.bid, ticker.ask) == (100, 99, 101)
    assert (ticker.bid_qty, ticker.ask_qty) == (2, 3)
    assert ticker.base_volume_24h == Decimal('10')
    assert ticker.quote_volume_24h == Decimal('987.123456789012345678')
    request.assert_awaited_once_with(validate=True)
    book.assert_not_awaited()
    assert await exchange.tickers(['UNKNOWN']) == {}
    row.update(volume=Decimal(0), quoteVolume=Decimal(0))
    ticker = (await exchange.tickers())['BTCUSDT']
    assert ticker.base_volume_24h == ticker.quote_volume_24h == Decimal(0)


async def test_empty_selection_does_not_fetch(monkeypatch: pytest.MonkeyPatch):
  """An empty selection must not spend quota on the larger full-ticker response."""
  async with MexcMarket.public() as venue:
    request = AsyncMock(side_effect=AssertionError('unexpected request'))
    monkeypatch.setattr(venue.client.spot.http.market, 'ticker_24hr', request)
    assert await (await venue.exchange('spot')).tickers([]) == {}
    request.assert_not_awaited()
