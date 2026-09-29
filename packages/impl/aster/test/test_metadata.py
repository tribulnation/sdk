"""Cached symbol metadata, missing-symbol errors and native request sizing."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import Any
import pytest
from typed_aster.futures.market.depth import Depth as FuturesDepth
from typed_aster.futures.market.exchange_info import ExchangeInfoEndpoint
from typed_aster.futures.market.funding_info import FundingInfoEndpoint
from typed_aster.futures.market.premium_index import PremiumIndex
from tribulnation.aster import AsterMarket
from tribulnation.aster.market.exchanges import join_perp_stats, join_tickers
from tribulnation.aster.market.markets import PerpMarket, error_code
from tribulnation.sdk import BadRequest
from tribulnation.sdk.core import MissingData


def contract(symbol: str, status: str = 'TRADING') -> dict[str, Any]:
  """A native perpetual definition with the filters the SDK maps."""
  return {
    'symbol': symbol,
    'status': status,
    'contractType': 'PERPETUAL',
    'marginAsset': 'USDT',
    'filters': [
      {
        'filterType': 'PRICE_FILTER',
        'tickSize': Decimal('0.1'),
        'minPrice': Decimal('0.1'),
        'maxPrice': Decimal(0),
      },
      {
        'filterType': 'LOT_SIZE',
        'stepSize': Decimal('0.001'),
        'minQty': Decimal('0.001'),
        'maxQty': Decimal(1000),
      },
      {'filterType': 'MIN_NOTIONAL', 'notional': Decimal(5)},
    ],
  }


async def test_catalogue_is_cached_and_refetched_on_request(
  monkeypatch: pytest.MonkeyPatch,
):
  """Discovery and rules share one catalogue read; `refetch` renews it."""
  info = AsyncMock(
    return_value={'symbols': [contract('BTCUSDT'), contract('OLDUSDT', 'CLOSE')]}
  )
  monkeypatch.setattr(ExchangeInfoEndpoint, 'exchange_info', info)
  exchange = AsterMarket.new(public=True).perp
  assert await exchange.markets() == ['BTCUSDT']
  market = await exchange.market('BTCUSDT')
  rules = await market.rules()
  assert rules.tick_size == Decimal('0.1') and rules.min_value == 5
  assert rules.fixed_max_price is None and rules.fee_asset == 'USDT'
  assert info.await_count == 1
  await market.rules(refetch=True)
  assert info.await_count == 2
  with pytest.raises(ValueError, match='Unknown Aster perpetual'):
    await exchange.market('OLDUSDT')
  info.return_value = {'symbols': []}
  with pytest.raises(ValueError, match='not trading'):
    await market.rules(refetch=True)


async def test_missing_premium_row_is_missing_data(monkeypatch: pytest.MonkeyPatch):
  """An omitted symbol surfaces as `MissingData`, not a leaked `StopIteration`."""
  monkeypatch.setattr(PremiumIndex, 'premium_index', AsyncMock(return_value=[]))
  market = PerpMarket(shared=AsterMarket.new(public=True).shared, symbol='BTCUSDT')
  with pytest.raises(MissingData):
    await market.index()


@pytest.mark.parametrize(
  'levels,limit', [(None, 1000), (1, 5), (5, 5), (6, 10), (101, 500)]
)
async def test_depth_requests_the_smallest_native_limit(
  levels: int | None, limit: int, monkeypatch: pytest.MonkeyPatch
):
  """The native request covers the requested levels without overfetching."""
  endpoint = AsyncMock(return_value={'bids': [], 'asks': []})
  monkeypatch.setattr(FuturesDepth, 'depth', endpoint)
  market = PerpMarket(shared=AsterMarket.new(public=True).shared, symbol='BTCUSDT')
  await market.depth(levels=levels)
  assert endpoint.await_args is not None
  assert endpoint.await_args.kwargs['limit'] == limit
  with pytest.raises(ValueError):
    await market.depth(levels=1001)


def test_error_code_tolerates_unexpected_payloads():
  """Only a native `{code: int}` payload yields a code."""
  assert error_code(BadRequest(400, {'code': -2013, 'msg': 'x'})) == -2013
  assert error_code(BadRequest(400, 'gateway timeout')) is None
  assert error_code(BadRequest('no payload')) is None


def test_empty_ticker_sides_are_none():
  """A zero native price marks an empty side or an untraded symbol, not a quote."""
  stats: list[Any] = [
    {'symbol': 'ALLOUSDT', 'lastPrice': Decimal(0), 'volume': 0, 'quoteVolume': 0}
  ]
  quotes: list[Any] = [
    {
      'symbol': 'ALLOUSDT',
      'bidPrice': Decimal('0.2'),
      'bidQty': Decimal(5),
      'askPrice': Decimal(0),
      'askQty': Decimal(0),
    }
  ]
  ticker = join_tickers(stats, quotes, {'ALLOUSDT'})['ALLOUSDT']
  assert ticker.bid == Decimal('0.2') and ticker.bid_qty == 5
  assert ticker.ask is None and ticker.ask_qty is None and ticker.last is None


def test_perp_stats_join_premiums_with_intervals():
  """Bulk rows are restricted to the selected symbols; a null interval stays `None`."""
  time = datetime(2026, 9, 25, 16, tzinfo=timezone.utc)
  premiums: list[Any] = [
    {
      'symbol': symbol,
      'markPrice': Decimal(101),
      'indexPrice': Decimal(100),
      'lastFundingRate': Decimal('0.0001'),
      'nextFundingTime': time,
    }
    for symbol in ('BTCUSDT', 'SUSHIUSDT', 'OLDUSDT')
  ]
  configs: list[Any] = [
    {'symbol': 'BTCUSDT', 'fundingIntervalHours': 8},
    {'symbol': 'SUSHIUSDT', 'fundingIntervalHours': None},
  ]
  stats = join_perp_stats(premiums, configs, {'BTCUSDT', 'SUSHIUSDT', 'ETHUSDT'})
  assert set(stats) == {'BTCUSDT', 'SUSHIUSDT'}
  btc = stats['BTCUSDT']
  assert btc.index == 100 and btc.mark == 101 and btc.funding == Decimal('0.0001')
  assert btc.next_funding_time == time and btc.funding_interval == timedelta(hours=8)
  assert btc.open_interest is None
  assert stats['SUSHIUSDT'].funding_interval is None


async def test_null_funding_interval_is_missing_data(monkeypatch: pytest.MonkeyPatch):
  """A single-market read cannot report a null interval, so it fails loudly."""
  premium: dict[str, Any] = {
    'symbol': 'BTCUSDT',
    'lastFundingRate': Decimal(0),
    'nextFundingTime': datetime(2026, 9, 25, tzinfo=timezone.utc),
  }
  config: dict[str, Any] = {'symbol': 'BTCUSDT', 'fundingIntervalHours': None}
  monkeypatch.setattr(PremiumIndex, 'premium_index', AsyncMock(return_value=premium))
  monkeypatch.setattr(
    FundingInfoEndpoint, 'funding_info', AsyncMock(return_value=[config])
  )
  market = PerpMarket(shared=AsterMarket.new(public=True).shared, symbol='BTCUSDT')
  with pytest.raises(MissingData, match='no interval'):
    await market.next_funding()
