"""Native perpetual identities, base quantities, unsupported methods and page retries."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_core.exceptions import NetworkError as TypedNetworkError
from typed_core.validation import validator
from typed_kraken import Kraken
from typed_kraken.charts.candles import Candles, ChartCandlesResult
from typed_kraken.futures.tickers import Tickers
from typed_kraken.futures.instruments import FuturesInstrument
from typed_kraken.schemas import FuturesMarketTicker

from tribulnation.sdk import Context, NetworkError
from tribulnation.kraken.market.impl.mixin import Shared
from tribulnation.kraken.market.impl.perp_candles import PAGE_SIZE
from tribulnation.kraken.market.impl.perp_data import (
  parse_book,
  parse_rules,
  parse_stats,
  parse_ticker,
  select_perps,
)
from tribulnation.kraken.market.perp_exchange import PerpExchange
from tribulnation.kraken.market.perp_market import PerpMarket
from tribulnation.kraken.market.venue import KrakenMarket

START = datetime(2026, 9, 1, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


def instrument(symbol: str = 'PF_XBTUSD') -> FuturesInstrument:
  """Native required fields and the precision of the BTC linear perpetual."""
  return {
    'symbol': symbol,
    'type': 'flexible_futures',
    'tradeable': True,
    'tradfi': False,
    'platformsPermitted': [],
    'countriesBanned': [],
    'isExpired': False,
    'quote': 'USD',
    'base': 'BTC',
    'contractSize': 1,
    'contractValueTradePrecision': 4,
    'tickSize': 1,
    'maxPositionSize': 1200,
  }


def ticker(symbol: str = 'PF_XBTUSD') -> FuturesMarketTicker:
  """Native market snapshot with absolute funding figures, not a relative estimate."""
  return {
    'symbol': symbol,
    'tag': 'perpetual',
    'pair': 'XBT:USD',
    'markPrice': 100,
    'vol24h': 20.3,
    'volumeQuote': 2030,
    'openInterest': 30.5,
    'suspended': False,
    'indexPrice': 99,
    'postOnly': False,
    'change24h': 1,
    'last': 100,
    'bid': 99,
    'ask': 101,
    'bidSize': 0.0123,
    'askSize': 0.0456,
    'fundingRate': 0.15,
    'fundingRatePrediction': 0.16,
  }


def response(indices: list[int], *, more: bool = False) -> ChartCandlesResult:
  """Validate millisecond/decimal-string wire fixtures before the SDK sees them."""
  return validator(ChartCandlesResult).python(
    {
      'candles': [
        {
          'time': int((START + i * MINUTE).timestamp() * 1000),
          'open': '10',
          'high': '12',
          'low': '8',
          'close': '11',
          'volume': '0.1234',
        }
        for i in indices
      ],
      'more_candles': more,
    }
  )


@pytest.fixture
def shared() -> Shared:
  """Use a real public client with prequalified metadata and no live reads."""
  return Shared(
    client=Kraken.new(public=True),
    perp_instruments={'PF_XBTUSD': instrument()},
    fee_asset='ZUSD',
  )


@pytest.fixture
def market(shared: Shared) -> PerpMarket:
  """Construct the qualified reference market."""
  return PerpMarket(shared=shared, symbol='PF_XBTUSD')


def test_discovery_uses_product_fields_not_symbol_prefix():
  """Inverse, dated, expired, suspended and non-unit products never leak into perp."""
  good = instrument('NATIVE_WITHOUT_PREFIX')
  rows = [
    good,
    {**instrument('inverse'), 'type': 'futures_inverse'},
    {**instrument('dated'), 'lastTradingTime': START},
    {**instrument('expired'), 'isExpired': True},
    {**instrument('tradfi'), 'tradfi': True},
    {**instrument('multiplier'), 'contractSize': 10},
    instrument('suspended'),
    instrument('no_ticker'),
  ]
  snapshots = [ticker(row['symbol']) for row in rows[:-1]]
  snapshots[-1]['suspended'] = True
  assert list(select_perps(rows, snapshots)) == ['NATIVE_WITHOUT_PREFIX']


@pytest.mark.parametrize('precision,step', [(4, '0.0001'), (3, '0.001'), (-3, '1000')])
def test_rules_precision_and_unknown_order_limits(precision: int, step: str):
  """Negative precision describes a large base-unit grid; position limits are not order limits."""
  rules = parse_rules(
    {**instrument(), 'contractValueTradePrecision': precision}, fee_asset='ZUSD'
  )
  assert rules.step_size == rules.fixed_min_qty == Decimal(step)
  assert rules.fee_asset == 'ZUSD' and rules.api
  assert rules.max_qty is None and rules.fees is None


def test_book_trims_after_sorting_native_ascending_bids():
  """Keep the actual best bid and its base quantity rather than the first wire row."""
  book = parse_book(
    {'bids': [(90, 3), (99, 0.1)], 'asks': [(101, 0.2), (102, 4)]}, levels=1
  )
  assert book.bids[0].price == 99 and book.bids[0].qty == Decimal('0.1')
  assert book.asks[0].price == 101


def test_native_ticker_units_and_no_absolute_funding_substitute():
  """No contract multiplication or mark-price division is needed for these fields."""
  row = ticker()
  mapped = parse_ticker(row)
  assert mapped.bid_qty == Decimal('0.0123')
  assert mapped.base_volume_24h == Decimal('20.3')
  stats = parse_stats(row)
  assert stats.index == 99 and stats.mark == 100
  assert stats.open_interest == Decimal('30.5')
  assert stats.funding is stats.next_funding_time is stats.funding_interval is None


async def test_exchange_identity_and_empty_selection(
  shared: Shared, monkeypatch: pytest.MonkeyPatch
):
  """An explicit empty selection makes no native request and unknown IDs are rejected."""
  request = AsyncMock()
  monkeypatch.setattr(Tickers, 'tickers', request)
  venue = KrakenMarket(shared=shared)
  exchange = await venue.exchange('perp')
  assert isinstance(exchange, PerpExchange)
  assert (await exchange.market('PF_XBTUSD')).id == 'kraken:perp:PF_XBTUSD'
  assert await exchange.tickers([]) == await exchange.perp_stats([]) == {}
  request.assert_not_awaited()
  with pytest.raises(ValueError):
    await exchange.market('PI_XBTUSD')


async def test_tickers_and_stats_filter_unknown_and_duplicate_ids(
  shared: Shared, monkeypatch: pytest.MonkeyPatch
):
  """Only requested qualified contracts survive the bulk snapshot."""
  request = AsyncMock(
    return_value={
      'result': 'success',
      'serverTime': START,
      'tickers': [ticker(), ticker('PI_XBTUSD'), {'symbol': 'rr_xbtusd', 'last': 99}],
    }
  )
  monkeypatch.setattr(Tickers, 'tickers', request)
  exchange = PerpExchange(shared=shared)
  assert set(await exchange.tickers(['PF_XBTUSD', 'PF_XBTUSD', 'PI_XBTUSD'])) == {
    'PF_XBTUSD'
  }
  assert set(await exchange.perp_stats()) == {'PF_XBTUSD'}


async def test_sparse_pages_retry_failed_request_and_keep_half_open_bounds(
  market: PerpMarket, monkeypatch: pytest.MonkeyPatch
):
  """A middle empty window does not end history or replay an earlier successful page."""
  request = AsyncMock(
    side_effect=[
      response([PAGE_SIZE, 1, 0, 1]),
      TypedNetworkError('transient'),
      response([]),
      response([2 * PAGE_SIZE, 2 * PAGE_SIZE + 1]),
    ]
  )
  monkeypatch.setattr(Candles, 'candles', request)
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    rows = await market.candles('1m', START, START + (2 * PAGE_SIZE + 1) * MINUTE)
  assert [r.time for r in rows] == [
    START + MINUTE,
    START,
    START + 2 * PAGE_SIZE * MINUTE,
  ]
  assert rows[0].volume == Decimal('0.1234')
  assert [call.kwargs['from_'] for call in request.await_args_list] == [
    START,
    START + PAGE_SIZE * MINUTE,
    START + PAGE_SIZE * MINUTE,
    START + 2 * PAGE_SIZE * MINUTE,
  ]
  assert request.await_args_list[0].kwargs[
    'to'
  ] == START + PAGE_SIZE * MINUTE - timedelta(seconds=1)


async def test_exact_page_boundary_has_every_open_once(
  market: PerpMarket, monkeypatch: pytest.MonkeyPatch
):
  """The final row of page one and first row of page two are both retained."""
  request = AsyncMock(
    side_effect=[response(list(range(PAGE_SIZE))), response([PAGE_SIZE, PAGE_SIZE + 1])]
  )
  monkeypatch.setattr(Candles, 'candles', request)
  rows = await market.candles('1m', START, START + (PAGE_SIZE + 1) * MINUTE)
  assert [r.time for r in rows] == [START + i * MINUTE for i in range(PAGE_SIZE + 1)]


async def test_fractional_bounds_and_forming_candle(
  market: PerpMarket, monkeypatch: pytest.MonkeyPatch
):
  """Wire seconds include the forming open while filtering subsecond SDK boundaries."""
  request = AsyncMock(return_value=response([0, 1, 2]))
  monkeypatch.setattr(Candles, 'candles', request)
  rows = await market.candles(
    '1m', START + timedelta(microseconds=1), START + MINUTE + timedelta(microseconds=1)
  )
  assert [r.time for r in rows] == [START + MINUTE]
  assert request.await_args.kwargs['to'] == START + MINUTE


async def test_empty_bounds_and_bad_levels_make_no_request(
  market: PerpMarket, monkeypatch: pytest.MonkeyPatch
):
  """Invalid input or an empty range is handled before network access."""
  request = AsyncMock()
  monkeypatch.setattr(Candles, 'candles', request)
  assert await market.candles('1m', START, START) == []
  request.assert_not_awaited()
  with pytest.raises(ValueError, match='positive'):
    await market.depth(levels=0)
  with pytest.raises(ValueError, match='timezone-aware'):
    market.candles('1m', START.replace(tzinfo=None), START)


async def test_unexpected_truncation_is_visible(
  market: PerpMarket, monkeypatch: pytest.MonkeyPatch
):
  """A changed native cap cannot silently discard part of a requested range."""
  monkeypatch.setattr(
    Candles, 'candles', AsyncMock(return_value=response([0], more=True))
  )
  with pytest.raises(ValueError, match='truncated'):
    await market.candles('1m', START, START + MINUTE)


async def test_unqualified_methods_remain_explicit(market: PerpMarket):
  """Private APIs, streams and synthesized next funding are not enabled by REST support."""
  with pytest.raises(NotImplementedError):
    await market.next_funding()
  with pytest.raises(NotImplementedError):
    market.depth_stream()
  with pytest.raises(NotImplementedError):
    await market.fees()
  with pytest.raises(NotImplementedError):
    await market.perp_position()


async def test_funding_settlement_conversion_and_inclusive_bounds(
  market: PerpMarket, monkeypatch: pytest.MonkeyPatch
):
  """Filter the documented hour-end settlement, not the earlier native period start."""
  from typed_kraken.futures.historical_funding_rates import HistoricalFundingRates

  request = AsyncMock(
    return_value={
      'result': 'success',
      'serverTime': START,
      'rates': [
        {
          'timestamp': START + timedelta(hours=i),
          'relativeFundingRate': 0.001 * (i + 1),
          'fundingRate': 20 + i,
        }
        for i in range(3)
      ],
    }
  )
  monkeypatch.setattr(HistoricalFundingRates, 'historical_funding_rates', request)
  rows = await market.funding_rates(
    START + timedelta(hours=2), START + timedelta(hours=2)
  )
  assert len(rows) == 1
  assert rows[0].time == START + timedelta(hours=2)
  assert rows[0].rate == Decimal('0.002')
  all_rows = await market.funding_rates()
  assert [r.time for r in all_rows] == [START + timedelta(hours=i) for i in [1, 2, 3]]
  assert request.await_args.args == ('PF_XBTUSD',)
  assert request.await_args.kwargs == {}
  with pytest.raises(ValueError, match='timezone-aware'):
    market.funding_rates(START.replace(tzinfo=None))
  with pytest.raises(ValueError, match='precede'):
    market.funding_rates(START + MINUTE, START)
