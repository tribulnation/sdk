"""Cached symbol metadata, missing-symbol errors and native request sizing."""

from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import Any
import pytest
from typed_aster.futures.market.depth import Depth as FuturesDepth
from typed_aster.futures.market.exchange_info import ExchangeInfoEndpoint
from typed_aster.futures.market.premium_index import PremiumIndex
from tribulnation.aster import AsterMarket
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
