"""Binance ticker snapshots use only the bulk public spot endpoint."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_binance.spot.http.market.ticker_24hr import Ticker24hr

from tribulnation.binance import BinanceMarket
from tribulnation.binance.market.impl.mixin import Shared


@pytest.fixture(autouse=True)
def symbols(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
  """Keep public discovery deterministic without real exchange requests."""
  request = AsyncMock(return_value={'BTCUSDT': {}, 'ETHUSDT': {}})
  monkeypatch.setattr(Shared, 'load_spot_symbols', request)
  return request


def ticker(symbol: str, **overrides: Decimal) -> dict[str, str | Decimal]:
  """Fields the SDK consumes, already decimal-decoded by the typed client."""
  return {
    'symbol': symbol,
    'lastPrice': Decimal('1.000000000000000001'),
    'bidPrice': Decimal('1'),
    'bidQty': Decimal('2'),
    'askPrice': Decimal('3'),
    'askQty': Decimal('4'),
    'volume': Decimal('5'),
    **overrides,
  }


async def test_bulk_spot_tickers_preserve_decimal_fields(
  monkeypatch: pytest.MonkeyPatch,
):
  """One bulk ticker request yields resolvable symbols without per-market requests."""
  request = AsyncMock(return_value=[ticker('BTCUSDT'), ticker('ETHUSDT')])
  monkeypatch.setattr(Ticker24hr, 'ticker_24hr', request)
  async with BinanceMarket.new(public=True) as sdk:
    result = await (await sdk.exchange('spot')).tickers()
  assert set(result) == {'BTCUSDT', 'ETHUSDT'}
  assert result['BTCUSDT'].last == Decimal('1.000000000000000001')
  assert result['BTCUSDT'].bid_qty == Decimal('2')
  assert result['BTCUSDT'].base_volume_24h == Decimal('5')
  request.assert_awaited_once_with(type='FULL')


async def test_empty_selection_avoids_network(
  monkeypatch: pytest.MonkeyPatch, symbols: AsyncMock
):
  """An empty requested subset means no markets, not all markets."""
  request = AsyncMock()
  monkeypatch.setattr(Ticker24hr, 'ticker_24hr', request)
  async with BinanceMarket.new(public=True) as sdk:
    assert await (await sdk.exchange('spot')).tickers([]) == {}
  request.assert_not_awaited()
  symbols.assert_not_awaited()


async def test_retired_ticker_ids_are_not_returned(monkeypatch: pytest.MonkeyPatch):
  """Every ticker ID can be resolved through the same cached market discovery."""
  monkeypatch.setattr(
    Ticker24hr,
    'ticker_24hr',
    AsyncMock(return_value=[ticker('BTCUSDT'), ticker('NBTUSDT')]),
  )
  async with BinanceMarket.new(public=True) as sdk:
    exchange = await sdk.exchange('spot')
    assert set(await exchange.tickers()) == {'BTCUSDT'}
    with pytest.raises(ValueError, match='not found'):
      await exchange.tickers(['NBTUSDT'])


async def test_subset_and_unavailable_book(monkeypatch: pytest.MonkeyPatch):
  """An empty book has absent quotes, while zero traded volume remains real zero."""
  request = AsyncMock(
    return_value=[
      ticker('BTCUSDT', bidQty=Decimal(0), askQty=Decimal(0), volume=Decimal(0)),
      ticker('ETHUSDT'),
    ]
  )
  monkeypatch.setattr(Ticker24hr, 'ticker_24hr', request)
  async with BinanceMarket.new(public=True) as sdk:
    result = await (await sdk.exchange('spot')).tickers(['BTCUSDT'])
  assert set(result) == {'BTCUSDT'}
  assert result['BTCUSDT'].bid is None
  assert result['BTCUSDT'].ask_qty is None
  assert result['BTCUSDT'].base_volume_24h == 0


async def test_missing_requested_symbol_is_not_silent(monkeypatch: pytest.MonkeyPatch):
  """Missing requested markets fail rather than masquerading as a full snapshot."""
  monkeypatch.setattr(Ticker24hr, 'ticker_24hr', AsyncMock(return_value=[]))
  async with BinanceMarket.new(public=True) as sdk:
    with pytest.raises(ValueError, match='not found'):
      await (await sdk.exchange('spot')).tickers(['UNKNOWN'])
