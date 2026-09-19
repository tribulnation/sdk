"""Deribit public product boundaries, native units, candle paging and lifecycle."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import AsyncIterator, Awaitable, Callable, cast
from typed_core.exceptions import NetworkError as TypedNetworkError
from typed_deribit import Deribit
from typed_deribit.market_data.get_instruments import InstrumentItem
from typed_deribit.market_data.get_tradingview_chart_data import TradingviewChartData

from tribulnation.deribit import DeribitMarket
from tribulnation.deribit.market.common import Shared
from tribulnation.deribit.market.candles import parse_candles
from tribulnation.deribit.market.markets import LinearPerpMarket, NativeSpotMarket
from tribulnation.sdk import Context, MarketSDK, NetworkError, accounts

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def instrument(symbol: str = 'BTC_USDC-PERPETUAL', **changes: object) -> InstrumentItem:
  """Minimal native definition, including a small contract size distinct from book units."""
  return cast(
    InstrumentItem,
    dict(
      instrument_name=symbol,
      kind='future',
      is_active=True,
      settlement_period='perpetual',
      instrument_type='linear',
      settlement_currency='USDC',
      quote_currency='USDC',
      base_currency='BTC',
      contract_size=0.0001,
    )
    | changes,
  )


def shared_client(api: object, *, streams: object = None) -> Shared:
  """Use an isolated public transport with a preloaded supported inventory."""
  return Shared(
    client=cast(Deribit, SimpleNamespace(market_data=api, streams=streams)),
    inventory={
      'instruments': {
        'BTC_USDC-PERPETUAL': instrument(),
        'BTC_USDT': instrument('BTC_USDT', kind='spot', quote_currency='USDT'),
      }
    },
  )


def chart(*times: datetime) -> TradingviewChartData:
  """An aligned parallel-array candle payload with distinguishable OHLC values."""
  return {
    'status': 'ok',
    'ticks': [int(t.timestamp() * 1000) for t in times],
    'open': [10.0] * len(times),
    'high': [12.0] * len(times),
    'low': [8.0] * len(times),
    'close': [11.0] * len(times),
    'volume': [2.0] * len(times),
    'cost': [22.0] * len(times),
  }


async def test_discovery_preserves_ids_and_excludes_unsupported_products():
  """Do not allow dated, inverse, inactive, cross-settled or combo contracts through."""
  request = AsyncMock(
    return_value=[
      instrument(),
      instrument('INVERSE', instrument_type='reversed'),
      instrument('DATED', settlement_period='month'),
      instrument('COMBO', kind='future_combo'),
      instrument('INACTIVE', is_active=False),
      instrument('QUANTO', settlement_currency='BTC'),
      instrument('BTC_USDT', kind='spot'),
      instrument('BTC_USDC', kind='spot', is_cbe_routed=True),
    ]
  )
  shared = shared_client(SimpleNamespace(get_instruments=request))
  shared.inventory.clear()
  venue = DeribitMarket(shared=shared)
  perp = await venue.perp_exchange('perp')
  assert await perp.markets() == ['BTC_USDC-PERPETUAL']
  assert (
    await perp.market('BTC_USDC-PERPETUAL')
  ).id == 'deribit:perp:BTC_USDC-PERPETUAL'
  assert (await venue.market('spot:BTC_USDT')).CANDLE_INTERVALS == {
    '1m',
    '5m',
    '15m',
    '1h',
  }
  routed = await venue.market('spot:BTC_USDC')
  assert not routed.CANDLE_INTERVALS
  with pytest.raises(ValueError, match='not served'):
    await routed.candles('1h', NOW, NOW + timedelta(hours=1))
  for symbol in [
    'INVERSE',
    'DATED',
    'COMBO',
    'INACTIVE',
    'QUANTO',
    'BTC_USDT',
    'UNKNOWN',
  ]:
    with pytest.raises(ValueError, match='unsupported'):
      await perp.market(symbol)
  with pytest.raises(ValueError, match='exchange'):
    await venue.exchange('future')
  assert request.await_count == 1


async def test_empty_discovery_is_cached_and_explicit_refresh_reloads():
  """An empty response must not cause repeated discovery calls and rate-limit churn."""
  request = AsyncMock(side_effect=[[], [instrument()]])
  shared = shared_client(SimpleNamespace(get_instruments=request))
  shared.inventory.clear()
  assert await shared.symbols() == await shared.symbols() == {}
  assert request.await_count == 1
  assert list(await shared.symbols(refetch=True)) == ['BTC_USDC-PERPETUAL']


async def test_book_units_sorting_limits_and_unsupported_sizes():
  """Native linear quantities are already base coins, despite contract_size=0.0001."""
  request = AsyncMock(
    return_value={
      'bids': [(98.0, 3.0), (99.0, 2.0)],
      'asks': [(102.0, 5.0), (101.0, 4.0)],
    }
  )
  market = LinearPerpMarket(
    shared=shared_client(SimpleNamespace(get_order_book=request)),
    symbol='BTC_USDC-PERPETUAL',
  )
  book = await market.depth(levels=1)
  assert (book.bids[0].price, book.bids[0].qty) == (99, 2)
  assert (book.asks[0].price, book.asks[0].qty) == (101, 4)
  await market.depth(levels=51)
  assert request.await_args is not None and request.await_args.kwargs['depth'] == 100
  sizes: list[int] = [0, -1, 101, True]
  for size in sizes:
    with pytest.raises(ValueError):
      await market.depth(levels=size)
  assert request.await_count == 2


async def test_tickers_query_only_requested_product_scopes_and_keep_nulls():
  """An unrelated option response must never enter spot/futures summary validation."""
  request = AsyncMock(
    return_value=[
      dict(
        instrument_name='BTC_USDC-PERPETUAL',
        last=None,
        bid_price=99.0,
        ask_price=None,
        volume=2.0,
      ),
      dict(
        instrument_name='OPTION', last=1.0, bid_price=1.0, ask_price=2.0, volume=3.0
      ),
    ]
  )
  exchange = await DeribitMarket(
    shared=shared_client(SimpleNamespace(get_book_summary_by_currency=request))
  ).perp_exchange('perp')
  assert await exchange.tickers([]) == await exchange.tickers(['UNKNOWN']) == {}
  request.assert_not_called()
  rows = await exchange.tickers(['BTC_USDC-PERPETUAL'])
  assert set(rows) == {'BTC_USDC-PERPETUAL'}
  ticker = rows['BTC_USDC-PERPETUAL']
  assert ticker.bid == 99 and ticker.last is None and ticker.ask is None
  assert ticker.base_volume_24h == 2 and ticker.bid_qty is None
  request.assert_awaited_once_with(currency='USDC', kind='future')


async def test_stats_use_native_index_and_base_interest_without_funding_forecast():
  """No midpoint index, contract-size multiplier or invented next-payment fields."""
  request = AsyncMock(
    return_value={'index_price': 100.5, 'mark_price': 101.0, 'open_interest': 2.0}
  )
  shared = shared_client(SimpleNamespace(ticker=request))
  exchange = await DeribitMarket(shared=shared).perp_exchange('perp')
  assert await exchange.perp_stats([]) == {}
  row = (await exchange.perp_stats())['BTC_USDC-PERPETUAL']
  assert row.index == Decimal('100.5') and row.mark == 101 and row.open_interest == 2
  assert row.funding is row.next_funding_time is row.funding_interval is None
  request.return_value = {'index_price': 100.5, 'mark_price': 101.0}
  assert (await exchange.perp_stats())['BTC_USDC-PERPETUAL'].open_interest is None


async def test_sparse_windows_retry_only_failed_request_and_remove_boundary_rows():
  """A successful page is not replayed; no_data in the middle does not end history."""
  middle = NOW + timedelta(minutes=1000)
  last = NOW + timedelta(minutes=2000)
  end = last + timedelta(minutes=1)
  request = AsyncMock(
    side_effect=[
      chart(NOW - timedelta(minutes=1), NOW, NOW, middle),
      TypedNetworkError('transient'),
      {'status': 'no_data'},
      chart(last, end),
    ]
  )
  market = NativeSpotMarket(
    shared=shared_client(SimpleNamespace(get_tradingview_chart_data=request)),
    symbol='BTC_USDT',
  )
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    pages = [p async for p in market.candles('1m', NOW, end)]
  assert [[r.time for r in page] for page in pages] == [[NOW], [], [last]]
  assert request.await_count == 4
  assert request.await_args_list[1] == request.await_args_list[2]
  assert request.await_args_list[0].kwargs['end_timestamp'] == middle - timedelta(
    milliseconds=1
  )
  assert all(c.kwargs['transport'] == 'ws' for c in request.await_args_list)
  first = pages[0][0]
  assert (
    first.open,
    first.high,
    first.low,
    first.close,
    first.volume,
    first.quote_volume,
  ) == (10, 12, 8, 11, 2, 22)


async def test_fractional_bounds_and_equal_window():
  """Filter submillisecond SDK bounds after wire conversion without requesting equal bounds."""
  end = NOW + timedelta(minutes=1, microseconds=1)
  request = AsyncMock(return_value=chart(NOW, NOW + timedelta(minutes=1)))
  market = NativeSpotMarket(
    shared=shared_client(SimpleNamespace(get_tradingview_chart_data=request)),
    symbol='BTC_USDT',
  )
  assert await market.candles('1m', NOW, NOW) == []
  request.assert_not_called()
  rows = await market.candles('1m', NOW + timedelta(microseconds=1), end)
  assert [r.time for r in rows] == [NOW + timedelta(minutes=1)]
  assert request.await_args is not None and request.await_args.kwargs[
    'end_timestamp'
  ] == end.replace(microsecond=0)
  with pytest.raises(ValueError):
    market.candles('4h', NOW, end)
  with pytest.raises(ValueError):
    market.candles('1d', NOW, end)
  with pytest.raises(ValueError):
    market.candles('1m', NOW.replace(tzinfo=None), end)
  with pytest.raises(ValueError):
    market.candles('1m', end, NOW)


@pytest.mark.parametrize(
  'payload',
  [
    {'status': 'ok', 'ticks': [0]},
    {
      'status': 'ok',
      'ticks': [0],
      'open': [],
      'high': [1.0],
      'low': [1.0],
      'close': [1.0],
    },
    {'status': 'no_data', 'ticks': [0]},
    {},
  ],
)
def test_malformed_arrays_fail_instead_of_silently_dropping_candles(
  payload: dict[str, object],
):
  """Typed optional fields and parallel arrays still require cross-field validation."""
  with pytest.raises(ValueError):
    parse_candles(cast(TradingviewChartData, payload))


def test_optional_candle_volumes_remain_unknown():
  """Unavailable turnover must not be inferred from close times volume."""
  row = chart(NOW)
  row.pop('volume')
  row.pop('cost')
  candle = parse_candles(row)[0]
  assert candle.volume is candle.quote_volume is candle.trades is None


async def test_stream_shares_upstream_and_copies_books_for_each_reader():
  """One subscribe survives until the last reader leaves; reader mutations are isolated."""
  queue: asyncio.Queue[dict[str, list[tuple[float, float]]]] = asyncio.Queue()

  async def iterate() -> AsyncIterator[dict[str, list[tuple[float, float]]]]:
    """Keep the fake native stream open until cancellation."""
    while True:
      yield await queue.get()

  class Stream:
    """Native stream with observable unsubscribe."""

    unsubscribe = AsyncMock()

    def __aiter__(self):
      """Read the shared queue."""
      return iterate()

  connect = AsyncMock(return_value=Stream())
  shared = shared_client(
    SimpleNamespace(),
    streams=SimpleNamespace(market_data=SimpleNamespace(book_grouped=connect)),
  )
  market = LinearPerpMarket(shared=shared, symbol='BTC_USDC-PERPETUAL')
  async with market.depth_stream() as first:
    async with market.depth_stream(levels=1) as second:
      queue.put_nowait({'bids': [(99.0, 2.0), (98.0, 3.0)], 'asks': [(101.0, 4.0)]})
      a, b = await asyncio.wait_for(
        asyncio.gather(anext(aiter(first)), anext(aiter(second))), 1
      )
      assert a is not b and a.bids[0] is not b.bids[0]
      assert len(a.bids) == 2 and len(b.bids) == 1 and b.bids[0].qty == 2
      assert connect.await_count == 1
    Stream.unsubscribe.assert_not_called()
  Stream.unsubscribe.assert_awaited_once()


async def test_unsupported_financial_methods_fail_before_network_reads():
  """Unqualified rules, funding and private operations must not fabricate results."""
  market = LinearPerpMarket(
    shared=shared_client(SimpleNamespace()), symbol='BTC_USDC-PERPETUAL'
  )
  calls: list[Callable[[], Awaitable[object]]] = [
    market.rules,
    market.next_funding,
    market.position,
    market.perp_collateral,
  ]
  for call in calls:
    with pytest.raises(NotImplementedError):
      await call()
  with pytest.raises(NotImplementedError):
    market.funding_rates()
  with pytest.raises(NotImplementedError):
    await market.place_order(
      {'type': 'LIMIT', 'qty': Decimal(1), 'price': Decimal(100)}
    )


async def test_sdk_uses_no_credentials_and_rejects_testnet():
  """Public routing ignores unresolved private credentials and never relabels testnet."""
  sdk = MarketSDK(
    {
      'alias': accounts.Deribit(
        client_id='$MISSING_DERIBIT_ID', client_secret='$MISSING_DERIBIT_SECRET'
      ),
      'test': accounts.Deribit(venue='deribit_testnet'),
    }
  )
  assert sdk.all_accounts['deribit'].public
  assert isinstance(await sdk.venue('alias'), DeribitMarket)
  with pytest.raises(ValueError, match='mainnet'):
    await sdk.venue('test')
