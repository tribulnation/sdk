"""Network-free conformance fixtures for MEXC's public perpetual exchange."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import cast
from typing_extensions import Literal

import pytest
from typed_mexc.schemas import ContractSpec, ContractTicker, FuturesCandle
from tribulnation.mexc import MexcMarket
from tribulnation.mexc.market.perp_market import PerpMarket
from tribulnation.sdk.market import Fees

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def contract(symbol: str = 'BTC_USDT', *, settlement: str = 'USDT') -> ContractSpec:
  """Only fields consumed by this SDK layer; Typed validates complete wire payloads."""
  return cast(
    ContractSpec,
    {
      'symbol': symbol,
      'settleCoin': settlement,
      'quoteCoin': 'USDT',
      'baseCoin': 'BTC',
      'contractSize': 0.0001,
      'apiAllowed': False,
      'state': 0,
      'priceUnit': 0.1,
      'volUnit': 1.0,
      'minVol': 2.0,
      'maxVol': 10000.0,
      'makerFeeRate': 0.0,
      'takerFeeRate': 0.0,
    },
  )


def ticker(symbol: str = 'BTC_USDT') -> ContractTicker:
  """A linear contract ticker with quantities expressed in contracts."""
  return cast(
    ContractTicker,
    {
      'symbol': symbol,
      'lastPrice': 100.1,
      'bid1': 100.0,
      'ask1': 100.2,
      'volume24': 10000.0,
      'holdVol': 20000.0,
      'indexPrice': 100.3,
      'fairPrice': 100.1,
      'fundingRate': -0.0001,
    },
  )


def candles(times: list[datetime]) -> FuturesCandle:
  """Parallel candle arrays with contract volume and quote turnover."""
  return {
    'time': times,
    'open': [100.1] * len(times),
    'high': [101.0] * len(times),
    'low': [99.0] * len(times),
    'close': [100.2] * len(times),
    'vol': [10000.0] * len(times),
    'amount': [100.15] * len(times),
    'realOpen': [100.1] * len(times),
    'realHigh': [101.0] * len(times),
    'realLow': [99.0] * len(times),
    'realClose': [100.2] * len(times),
  }


@pytest.fixture
async def venue(monkeypatch: pytest.MonkeyPatch) -> MexcMarket:
  """A real public root with mocked contract discovery, no credentials or network."""
  root = MexcMarket.public()
  monkeypatch.setattr(
    root.client.futures.http.market,
    'contract_info',
    AsyncMock(
      return_value={
        'success': True,
        'data': [contract(), contract('BTC_USD', settlement='BTC')],
      },
    ),
  )
  return root


async def test_perp_discovery_preserves_symbols_and_public_only_contracts(
  venue: MexcMarket,
):
  """Discover the new exchange without excluding apiAllowed=False public data."""
  assert await venue.exchanges() == [
    {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
    {'id': 'perp', 'type': 'perp', 'name': 'Linear Perpetuals'},
  ]
  exchange = await venue.perp_exchange('perp')
  assert await exchange.markets() == ['BTC_USDT']
  market = await exchange.market('BTC_USDT')
  assert market.id == 'mexc:perp:BTC_USDT'
  with pytest.raises(ValueError, match='Unknown MEXC'):
    await exchange.market('BTCUSDT')


async def test_bulk_tickers_and_stats_convert_contract_units(
  venue: MexcMarket, monkeypatch: pytest.MonkeyPatch
):
  """Convert volume/OI once, preserve negative funding and leave absent state unknown."""
  source = AsyncMock(
    return_value={'success': True, 'data': [ticker(), ticker('BTC_USD')]}
  )
  monkeypatch.setattr(venue.client.futures.http.market, 'ticker', source)
  exchange = await venue.perp_exchange('perp')
  tickers = await exchange.tickers()
  assert set(tickers) == {'BTC_USDT'}
  assert tickers['BTC_USDT'].last == Decimal('100.1')
  assert tickers['BTC_USDT'].base_volume_24h == Decimal('1')
  assert tickers['BTC_USDT'].bid_qty is None
  stats = (await exchange.perp_stats(['BTC_USDT']))['BTC_USDT']
  assert stats.open_interest == Decimal('2')
  assert stats.funding == Decimal('-0.0001')
  assert stats.next_funding_time is None and stats.funding_interval is None
  assert await exchange.tickers([]) == {}
  assert await exchange.perp_stats([]) == {}
  assert source.await_count == 2


@pytest.mark.parametrize('method', ['tickers', 'perp_stats'])
async def test_bulk_snapshot_rejects_unknown_requested_ids(
  venue: MexcMarket,
  monkeypatch: pytest.MonkeyPatch,
  method: Literal['tickers', 'perp_stats'],
):
  """Mixed known/unknown selections fail before querying the bulk snapshot."""
  source = AsyncMock()
  monkeypatch.setattr(venue.client.futures.http.market, 'ticker', source)
  exchange = await venue.perp_exchange('perp')
  with pytest.raises(ValueError, match='Unknown MEXC.*BTCUSDT'):
    await getattr(exchange, method)(['BTC_USDT', 'BTCUSDT'])
  source.assert_not_awaited()


@pytest.mark.parametrize('method', ['tickers', 'perp_stats'])
@pytest.mark.parametrize('selection', [None, ['BTC_USDT', 'ETH_USDT']])
async def test_bulk_snapshot_rejects_missing_expected_rows(
  venue: MexcMarket,
  monkeypatch: pytest.MonkeyPatch,
  method: Literal['tickers', 'perp_stats'],
  selection: list[str] | None,
):
  """Missing discovered or explicitly requested contracts cannot look successful."""
  api = venue.client.futures.http.market
  monkeypatch.setattr(
    api,
    'contract_info',
    AsyncMock(
      return_value={
        'success': True,
        'data': [contract(), contract('ETH_USDT')],
      }
    ),
  )
  monkeypatch.setattr(
    api,
    'ticker',
    AsyncMock(
      return_value={
        'success': True,
        'data': [ticker()],
      }
    ),
  )
  exchange = await venue.perp_exchange('perp')
  with pytest.raises(ValueError, match='snapshot missing markets: ETH_USDT'):
    await getattr(exchange, method)(selection)


@pytest.mark.parametrize('method', ['tickers', 'perp_stats'])
async def test_bulk_snapshot_empty_selection_has_no_network_calls(
  venue: MexcMarket,
  monkeypatch: pytest.MonkeyPatch,
  method: Literal['tickers', 'perp_stats'],
):
  """An explicit empty selection neither discovers contracts nor fetches tickers."""
  metadata = AsyncMock()
  snapshot = AsyncMock()
  api = venue.client.futures.http.market
  monkeypatch.setattr(api, 'contract_info', metadata)
  monkeypatch.setattr(api, 'ticker', snapshot)
  exchange = await venue.perp_exchange('perp')
  assert await getattr(exchange, method)([]) == {}
  metadata.assert_not_awaited()
  snapshot.assert_not_awaited()


@pytest.mark.parametrize('method', ['tickers', 'perp_stats'])
async def test_bulk_snapshot_selection_does_not_require_unselected_rows(
  venue: MexcMarket,
  monkeypatch: pytest.MonkeyPatch,
  method: Literal['tickers', 'perp_stats'],
):
  """Explicit subsets require only their own rows and ignore unrelated response rows."""
  api = venue.client.futures.http.market
  monkeypatch.setattr(
    api,
    'contract_info',
    AsyncMock(
      return_value={
        'success': True,
        'data': [contract(), contract('ETH_USDT')],
      }
    ),
  )
  monkeypatch.setattr(
    api,
    'ticker',
    AsyncMock(
      return_value={
        'success': True,
        'data': [ticker(), ticker('BTC_USD')],
      }
    ),
  )
  exchange = await venue.perp_exchange('perp')
  assert set(await getattr(exchange, method)(['BTC_USDT'])) == {'BTC_USDT'}


@pytest.mark.parametrize('method', ['tickers', 'perp_stats'])
async def test_bulk_snapshot_rejects_duplicate_selected_rows(
  venue: MexcMarket,
  monkeypatch: pytest.MonkeyPatch,
  method: Literal['tickers', 'perp_stats'],
):
  """Repeated market IDs must not silently overwrite conflicting snapshots."""
  monkeypatch.setattr(
    venue.client.futures.http.market,
    'ticker',
    AsyncMock(
      return_value={
        'success': True,
        'data': [ticker(), ticker()],
      }
    ),
  )
  exchange = await venue.perp_exchange('perp')
  with pytest.raises(ValueError, match='Duplicate MEXC perpetual ticker: BTC_USDT'):
    await getattr(exchange, method)()


async def test_zero_or_absent_book_sides_remain_unknown(
  venue: MexcMarket, monkeypatch: pytest.MonkeyPatch
):
  """Empty quotes never become zero-price opportunities; zero volume is retained."""
  row = ticker()
  row['bid1'] = 0
  del row['ask1']
  row['volume24'] = 0
  monkeypatch.setattr(
    venue.client.futures.http.market,
    'ticker',
    AsyncMock(return_value={'success': True, 'data': [row]}),
  )
  item = (await (await venue.perp_exchange('perp')).tickers())['BTC_USDT']
  assert item.bid is None and item.ask is None
  assert item.base_volume_24h == 0


async def test_public_funding_state_and_depth(
  venue: MexcMarket, monkeypatch: pytest.MonkeyPatch
):
  """Read exact variable settlement intervals and convert book size to base units."""
  api = venue.client.futures.http.market
  monkeypatch.setattr(
    api,
    'funding_rate',
    AsyncMock(
      return_value={
        'data': {'fundingRate': 0.0001, 'nextSettleTime': START, 'collectCycle': 4}
      }
    ),
  )
  monkeypatch.setattr(
    api,
    'depth',
    AsyncMock(
      return_value={
        'data': {'bids': [(100.0, 2000.0, 1)], 'asks': [(101.0, 3000.0, 1)]}
      }
    ),
  )
  market = await (await venue.perp_exchange('perp')).market('BTC_USDT')
  funding = await market.next_funding()
  assert funding.interval == timedelta(hours=4) and funding.time == START
  assert funding.rate == Decimal('0.0001')
  book = await market.depth()
  assert book.best_bid.qty == Decimal('0.2') and book.best_ask.qty == Decimal('0.3')


async def test_candle_pages_half_open_and_native_order(
  venue: MexcMarket, monkeypatch: pytest.MonkeyPatch
):
  """Cross 2000 opens without duplicates and convert contract volume to base volume."""
  boundary = START + timedelta(hours=2000)
  end = boundary + timedelta(hours=1)
  source = AsyncMock(
    side_effect=[
      {'data': candles([boundary, START + timedelta(hours=1), START, START])},
      {'data': candles([end, boundary, START])},
    ]
  )
  monkeypatch.setattr(venue.client.futures.http.market, 'candles', source)
  market = await (await venue.perp_exchange('perp')).market('BTC_USDT')
  pages = [page async for page in market.candles('1h', START, end)]
  assert [[c.time for c in page] for page in pages] == [
    [START + timedelta(hours=1), START],
    [boundary],
  ]
  assert pages[0][0].volume == Decimal('1')
  assert pages[0][0].quote_volume == Decimal('100.15')
  assert source.call_args_list[0].kwargs['end'] == boundary - timedelta(microseconds=1)
  assert source.call_args_list[1].kwargs['start'] == boundary


async def test_candles_continue_empty_windows_and_reject_mismatched_arrays(
  venue: MexcMarket, monkeypatch: pytest.MonkeyPatch
):
  """An empty window is not end-of-history; unequal column arrays fail visibly."""
  boundary = START + timedelta(hours=2000)
  source = AsyncMock(side_effect=[{'data': candles([])}, {'data': candles([boundary])}])
  monkeypatch.setattr(venue.client.futures.http.market, 'candles', source)
  market = await (await venue.perp_exchange('perp')).market('BTC_USDT')
  assert len(await market.candles('1h', START, boundary + timedelta(hours=1))) == 1
  invalid = candles([START])
  invalid['open'] = []
  source.side_effect = None
  source.return_value = {'data': invalid}
  with pytest.raises(ValueError, match='zip'):
    await market.candles('1h', START, START + timedelta(hours=1))


async def test_candle_empty_and_invalid_bounds_make_no_request(
  venue: MexcMarket, monkeypatch: pytest.MonkeyPatch
):
  """Equal bounds are empty; naive or reversed ranges and unknown intervals reject."""
  source = AsyncMock()
  monkeypatch.setattr(venue.client.futures.http.market, 'candles', source)
  market = await (await venue.perp_exchange('perp')).market('BTC_USDT')
  assert await market.candles('1h', START, START) == []
  with pytest.raises(ValueError, match='timezone-aware'):
    market.candles('1h', START.replace(tzinfo=None), START)
  with pytest.raises(ValueError, match='precede'):
    market.candles('1h', START + timedelta(hours=1), START)
  assert market.CANDLE_INTERVALS == {'1m', '5m', '15m', '1h', '4h', '1d'}
  source.assert_not_awaited()


async def test_funding_history_pages_with_inclusive_bounds_and_duplicates(
  venue: MexcMarket, monkeypatch: pytest.MonkeyPatch
):
  """Read every reported page, preserving native order and both exact endpoints."""
  end = START + timedelta(hours=8)
  source = AsyncMock(
    side_effect=[
      {
        'data': {
          'totalPage': 2,
          'resultList': [
            {'settleTime': end, 'fundingRate': 0.0001},
            {'settleTime': end + timedelta(hours=8), 'fundingRate': 0.0},
          ],
        }
      },
      {
        'data': {
          'totalPage': 2,
          'resultList': [
            {'settleTime': end, 'fundingRate': 0.0001},
            {'settleTime': START, 'fundingRate': -0.0001},
          ],
        }
      },
    ]
  )
  monkeypatch.setattr(venue.client.futures.http.market, 'funding_rate_history', source)
  market = await (await venue.perp_exchange('perp')).market('BTC_USDT')
  rows = await market.funding_rates(START, end)
  assert [row.time for row in rows] == [end, START]
  assert rows[-1].rate == Decimal('-0.0001')
  assert [call.kwargs['page_num'] for call in source.call_args_list] == [1, 2]


async def test_missing_public_payload_is_not_empty_success(
  venue: MexcMarket, monkeypatch: pytest.MonkeyPatch
):
  """Malformed success envelopes fail visibly rather than concealing missing coverage."""
  monkeypatch.setattr(
    venue.client.futures.http.market,
    'ticker',
    AsyncMock(return_value={'success': True}),
  )
  with pytest.raises(ValueError, match='did not return a list'):
    await (await venue.perp_exchange('perp')).tickers()


async def test_private_perpetual_methods_remain_unimplemented(venue: MexcMarket):
  """Public discovery does not broaden private futures access or permit trading."""
  market = await (await venue.perp_exchange('perp')).market('BTC_USDT')
  assert isinstance(market, PerpMarket)
  with pytest.raises(NotImplementedError, match='public data only'):
    await market.perp_position()
  with pytest.raises(NotImplementedError, match='public data only'):
    await market.place_order(
      {'type': 'LIMIT', 'qty': Decimal('1'), 'price': Decimal('1')}
    )


async def test_perpetual_rules_convert_contract_lots(venue: MexcMarket):
  """Public specs use base quantities and do not mistake web fees for API rates."""
  async with venue:
    market = await (await venue.perp_exchange('perp')).market('BTC_USDT')
    rules = await market.rules()
    assert rules.fee_asset == 'USDT'
    assert rules.tick_size == Decimal('0.1')
    assert rules.step_size == Decimal('0.0001')
    assert rules.fixed_min_qty == Decimal('0.0002')
    assert rules.max_qty == 1
    assert rules.api is False
    assert rules.fees is None


@pytest.mark.parametrize('enabled,state', [(True, 0), (False, 0), (True, 4)])
async def test_perpetual_standard_fees_are_api_scoped(
  venue: MexcMarket,
  monkeypatch: pytest.MonkeyPatch,
  enabled: bool,
  state: int,
):
  """Only active API-enabled contracts receive the API schedule, never web fees."""
  info = dict(contract(), apiAllowed=enabled, state=state)
  monkeypatch.setattr(
    venue.client.futures.http.market,
    'contract_info',
    AsyncMock(
      return_value={'success': True, 'data': [info]},
    ),
  )
  private = AsyncMock(side_effect=AssertionError('Private fee endpoint called'))
  monkeypatch.setattr(venue.client.futures.http.account, 'tiered_fee_rate', private)
  async with venue:
    market = await (await venue.perp_exchange('perp')).market('BTC_USDT')
    rules = await market.rules()
  expected = Fees.symmetric(maker=Decimal('0.0006'), taker=Decimal('0.0008'))
  assert rules.fees == (expected if enabled and state == 0 else None)
  private.assert_not_awaited()


async def test_perpetual_personal_fees_do_not_guess_api_channel(
  venue: MexcMarket,
  monkeypatch: pytest.MonkeyPatch,
):
  """Legacy account rates must not masquerade as verified API execution fees."""
  private = AsyncMock(side_effect=AssertionError('Legacy fee endpoint called'))
  monkeypatch.setattr(venue.client.futures.http.account, 'tiered_fee_rate', private)
  async with venue:
    market = await (await venue.perp_exchange('perp')).market('BTC_USDT')
    with pytest.raises(NotImplementedError, match='API fees are unverified'):
      await market.fees()
  private.assert_not_awaited()
