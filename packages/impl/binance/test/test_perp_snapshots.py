"""USD-M snapshots discover perpetuals and use public endpoints only."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_binance.usdm_futures.http.market.exchange_info import ExchangeInfoEndpoint
from typed_binance.usdm_futures.http.market.funding_info import FundingInfoEndpoint
from typed_binance.usdm_futures.http.market.open_interest import OpenInterestEndpoint
from typed_binance.usdm_futures.http.market.premium_index import PremiumIndex
from typed_binance.usdm_futures.http.market.ticker_24hr import Ticker24hr
from typed_binance.usdm_futures.http.market.ticker_book import TickerBook

from tribulnation.binance import BinanceMarket

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def interest_row(symbol: str) -> dict[str, str | Decimal]:
  """Return the decoded open-interest fields consumed by the SDK."""
  return {'symbol': symbol, 'openInterest': Decimal('12.000000000000000001')}


@pytest.fixture
def public_api(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
  """Patch real typed endpoint classes, leaving account routes unused."""
  calls = {
    'exchange_info': AsyncMock(
      return_value={
        'symbols': [
          {'symbol': 'BTCUSDT', 'contractType': 'PERPETUAL', 'status': 'TRADING'},
          {'symbol': 'ETHUSDT', 'contractType': 'PERPETUAL', 'status': 'TRADING'},
          {'symbol': 'DATED', 'contractType': 'CURRENT_QUARTER', 'status': 'TRADING'},
          {
            'symbol': 'PAUSED',
            'contractType': 'PERPETUAL',
            'status': 'PENDING_TRADING',
          },
        ]
      }
    ),
    'ticker_24hr': AsyncMock(
      return_value=[
        {
          'symbol': symbol,
          'lastPrice': Decimal('1.000000000000000001'),
          'volume': Decimal('0'),
        }
        for symbol in ('BTCUSDT', 'ETHUSDT', 'DATED', 'PAUSED')
      ]
    ),
    'ticker_book': AsyncMock(
      return_value=[
        {
          'symbol': 'BTCUSDT',
          'bidPrice': Decimal('1'),
          'bidQty': Decimal('2'),
          'askPrice': Decimal('3'),
          'askQty': Decimal('0'),
        },
      ]
    ),
    'premium_index': AsyncMock(
      return_value=[
        {
          'symbol': symbol,
          'indexPrice': Decimal('2'),
          'markPrice': Decimal('3'),
          'lastFundingRate': Decimal('-0.0001'),
          'nextFundingTime': NOW,
        }
        for symbol in ('BTCUSDT', 'ETHUSDT', 'DATED', 'PAUSED')
      ]
    ),
    'funding_info': AsyncMock(
      return_value=[
        {'symbol': 'ETHUSDT', 'fundingIntervalHours': 4},
      ]
    ),
    'open_interest': AsyncMock(side_effect=interest_row),
  }
  for cls, name in (
    (ExchangeInfoEndpoint, 'exchange_info'),
    (Ticker24hr, 'ticker_24hr'),
    (TickerBook, 'ticker_book'),
    (PremiumIndex, 'premium_index'),
    (FundingInfoEndpoint, 'funding_info'),
    (OpenInterestEndpoint, 'open_interest'),
  ):
    monkeypatch.setattr(cls, name, calls[name])
  return calls


async def test_tickers_keep_only_active_perpetuals(public_api: dict[str, AsyncMock]):
  """Bulk quotes retain Decimals, real zero volume and absent book sides."""
  async with BinanceMarket.new(public=True) as sdk:
    result = await (await sdk.perp_exchange('usdm')).tickers()
  assert set(result) == {'BTCUSDT', 'ETHUSDT'}
  assert result['BTCUSDT'].last == Decimal('1.000000000000000001')
  assert result['BTCUSDT'].base_volume_24h == 0
  assert result['BTCUSDT'].bid_qty == 2
  assert result['BTCUSDT'].ask is None
  assert result['ETHUSDT'].bid is None
  for name in ('exchange_info', 'ticker_24hr', 'ticker_book'):
    public_api[name].assert_awaited_once_with()
  public_api['open_interest'].assert_not_awaited()


async def test_stats_keep_base_units_and_funding_intervals(
  public_api: dict[str, AsyncMock],
):
  """Funding stays signed and relative; open interest is not price-multiplied."""
  async with BinanceMarket.new(public=True) as sdk:
    result = await (await sdk.perp_exchange('usdm')).perp_stats()
  assert set(result) == {'BTCUSDT', 'ETHUSDT'}
  btc = result['BTCUSDT']
  assert btc.index == 2 and btc.mark == 3
  assert btc.funding == Decimal('-0.0001')
  assert btc.next_funding_time == NOW
  assert btc.open_interest == Decimal('12.000000000000000001')
  assert btc.funding_interval == timedelta(hours=8)
  assert result['ETHUSDT'].funding_interval == timedelta(hours=4)
  assert public_api['open_interest'].await_count == 2
  public_api['premium_index'].assert_awaited_once_with()
  public_api['funding_info'].assert_awaited_once_with()


@pytest.mark.parametrize('method', ['tickers', 'perp_stats'])
async def test_empty_subset_avoids_all_network(
  public_api: dict[str, AsyncMock], method: str
):
  """An explicit empty selection never expands to the whole exchange."""
  async with BinanceMarket.new(public=True) as sdk:
    exchange = await sdk.perp_exchange('usdm')
    assert await getattr(exchange, method)([]) == {}
  for call in public_api.values():
    call.assert_not_awaited()


@pytest.mark.parametrize('method', ['tickers', 'perp_stats'])
async def test_requested_non_perpetual_is_rejected(
  public_api: dict[str, AsyncMock], method: str
):
  """Dated and unknown contracts cannot leak into the perpetual exchange."""
  async with BinanceMarket.new(public=True) as sdk:
    exchange = await sdk.perp_exchange('usdm')
    with pytest.raises(ValueError, match='not found'):
      await getattr(exchange, method)(['DATED'])


async def test_subset_deduplicates_interest_reads(public_api: dict[str, AsyncMock]):
  """Only the requested active market needs a per-symbol request."""
  async with BinanceMarket.new(public=True) as sdk:
    result = await (await sdk.perp_exchange('usdm')).perp_stats(['BTCUSDT', 'BTCUSDT'])
  assert set(result) == {'BTCUSDT'}
  public_api['open_interest'].assert_awaited_once_with('BTCUSDT')


@pytest.mark.parametrize(
  'method,endpoint', [('tickers', 'ticker_24hr'), ('perp_stats', 'premium_index')]
)
async def test_missing_snapshot_rows_fail_visibly(
  public_api: dict[str, AsyncMock], method: str, endpoint: str
):
  """A disappearing source row is not mistaken for complete collection."""
  public_api[endpoint].return_value = []
  async with BinanceMarket.new(public=True) as sdk:
    exchange = await sdk.perp_exchange('usdm')
    with pytest.raises(ValueError, match='not found'):
      await getattr(exchange, method)()


async def test_wrong_interest_symbol_rejected(public_api: dict[str, AsyncMock]):
  """An endpoint response must identify the market it was requested for."""
  public_api['open_interest'].side_effect = None
  public_api['open_interest'].return_value = {
    'symbol': 'WRONG',
    'openInterest': Decimal(1),
  }
  async with BinanceMarket.new(public=True) as sdk:
    with pytest.raises(ValueError, match='wrong symbol'):
      await (await sdk.perp_exchange('usdm')).perp_stats(['BTCUSDT'])


async def test_interest_failure_drains_sibling_requests(
  public_api: dict[str, AsyncMock],
):
  """A failed snapshot cannot leave reads running after the SDK owner closes."""
  started = asyncio.Event()
  stopped = asyncio.Event()

  async def interest(symbol: str):
    """Fail one read only after its sibling has entered its wait."""
    if symbol == 'BTCUSDT':
      await started.wait()
      raise ValueError('probe failure')
    started.set()
    try:
      await asyncio.Event().wait()
    finally:
      stopped.set()

  public_api['open_interest'].side_effect = interest
  async with BinanceMarket.new(public=True) as sdk:
    with pytest.raises(ValueError, match='probe failure'):
      await (await sdk.perp_exchange('usdm')).perp_stats()
    assert stopped.is_set()
