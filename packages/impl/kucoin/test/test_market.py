"""Public KuCoin identity, units, time-window paging and stream regressions."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import AsyncIterator, cast
from typed_core.exceptions import NetworkError as TypedNetworkError
from typed_kucoin import KuCoin
from typed_kucoin.futures.funding_fees.public_funding_history import (
  PublicFundingHistory,
)
from typed_kucoin.schemas import FuturesContract, SpotSymbol

from tribulnation.kucoin import KucoinMarket
from tribulnation.kucoin.market.common import Shared
from tribulnation.kucoin.market.markets import LinearPerpMarket, SpotMarket
from tribulnation.sdk import Context, MarketSDK, NetworkError
from tribulnation.sdk.market.types.candles import CandleInterval

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
D = Decimal


def contract(symbol: str = 'XBTUSDTM', **overrides: object) -> FuturesContract:
  """Only fields consumed by the adapter, with venue-native units."""
  return cast(
    FuturesContract,
    dict(
      symbol=symbol,
      expireDate=None,
      isInverse=False,
      quoteCurrency='USDT',
      settleCurrency='USDT',
      multiplier=0.001,
      status='Open',
      lotSize=1,
      tickSize=0.1,
      maxOrderQty=100000,
      indexPrice=100.5,
      markPrice=100.4,
      openInterest=1200,
      volumeOf24h=12.5,
      turnoverOf24h=1240.75,
    )
    | overrides,
  )


def spot_symbol() -> SpotSymbol:
  """Synthetic public spot constraints, with no account fee endpoint."""
  return cast(
    SpotSymbol,
    dict(
      symbol='BTC-USDT',
      enableTrading=True,
      feeCurrency='USDT',
      priceIncrement=D('0.1'),
      baseIncrement=D('0.000001'),
      baseMinSize=D('0.00001'),
      baseMaxSize=D('1000'),
      minFunds=D('0.1'),
      quoteMinSize=D('0.00001'),
    ),
  )


def shared_client(
  *, spot: object = None, futures: object = None, streams: object = None
) -> Shared:
  """Build an isolated fake transport with realistic instrument definitions."""
  return Shared(
    client=cast(KuCoin, SimpleNamespace(spot=spot, futures=futures, streams=streams)),
    spot={'BTC-USDT': spot_symbol()},
    perp={'XBTUSDTM': contract()},
  )


async def test_native_identity_discovery_and_explicit_contract_exclusions():
  """Keep Catalogue IDs and exclude inverse, dated and cross-settled contracts."""
  rows = [
    contract(),
    contract('INV', isInverse=True, multiplier=-1),
    contract('DATED', expireDate=NOW),
    contract('QUANTO', settleCurrency='BTC'),
    contract('CLOSED', status='Closed'),
  ]
  shared = shared_client(
    futures=SimpleNamespace(all_symbols=AsyncMock(return_value=rows))
  )
  shared.perp.clear()
  venue = KucoinMarket(shared=shared)
  assert [(e['id'], e['type']) for e in await venue.exchanges()] == [
    ('spot', 'spot'),
    ('perp', 'perp'),
  ]
  exchange = await venue.perp_exchange('perp')
  assert await exchange.markets() == ['XBTUSDTM']
  market = await venue.market('perp:XBTUSDTM')
  assert market.id == 'kucoin:perp:XBTUSDTM'
  assert (await venue.market('spot:BTC-USDT')).id == 'kucoin:spot:BTC-USDT'
  for symbol in ['INV', 'DATED', 'QUANTO', 'UNKNOWN']:
    with pytest.raises(ValueError, match='unsupported'):
      await exchange.market(symbol)
  with pytest.raises(ValueError, match='exchange'):
    await venue.exchange('futures')


async def test_rules_are_public_and_quantities_use_base_units():
  """Use minFunds for spot notional and convert every linear quantity constraint."""
  shared = shared_client()
  spot = SpotMarket(shared=shared, symbol='BTC-USDT')
  perp = LinearPerpMarket(
    shared=shared, symbol='XBTUSDTM', contract_multiplier=D('.001')
  )
  sr, pr = await spot.rules(), await perp.rules()
  assert sr.min_value == D('.1')
  assert sr.fees is None and pr.fees is None
  assert pr.step_size == pr.fixed_min_qty == D('.001')
  assert pr.max_qty == 100
  with pytest.raises(NotImplementedError):
    await perp.fees()
  with pytest.raises(NotImplementedError):
    await spot.position()
  with pytest.raises(NotImplementedError):
    await perp.perp_position()
  with pytest.raises(NotImplementedError):
    await spot.place_order({'type': 'LIMIT', 'qty': D(1), 'price': D(100)})


async def test_ticker_and_stats_selection_preserve_native_units():
  """Best-side sizes are lots, while volumeOf24h is already base volume."""
  row = dict(
    symbol='XBTUSDTM',
    price=D(100),
    bestBidPrice=D(99),
    bestBidSize=2,
    bestAskPrice=D(101),
    bestAskSize=3,
  )
  api = SimpleNamespace(
    all_symbols=AsyncMock(return_value=[contract()]),
    all_tickers=AsyncMock(return_value=[row]),
  )
  exchange = await KucoinMarket(shared=shared_client(futures=api)).perp_exchange('perp')
  assert await exchange.tickers([]) == {}
  api.all_tickers.assert_not_called()
  ticker = (await exchange.tickers(['XBTUSDTM']))['XBTUSDTM']
  assert (ticker.bid_qty, ticker.ask_qty, ticker.base_volume_24h) == (
    D('.002'),
    D('.003'),
    D('12.5'),
  )
  assert ticker.quote_volume_24h == D('1240.75')
  assert await exchange.tickers(['UNKNOWN']) == {}
  stats = (await exchange.perp_stats(['XBTUSDTM']))['XBTUSDTM']
  assert stats.open_interest == D('1.2')
  assert stats.index == D('100.5') and stats.mark == D('100.4')
  assert stats.funding is None


async def test_depth_normalizes_lots_and_rejects_unqualified_sizes():
  """No private full-book fallback for requests beyond the public limit."""
  request = AsyncMock(return_value={'bids': [(99.5, 2)], 'asks': [(100.5, 3)]})
  shared = shared_client(futures=SimpleNamespace(part_orderbook=request))
  market = LinearPerpMarket(
    shared=shared, symbol='XBTUSDTM', contract_multiplier=D('.001')
  )
  book = await market.depth(levels=100)
  assert book.bids[0].price == D('99.5') and book.bids[0].qty == D('.002')
  assert request.await_args is not None and request.await_args.args == ('100',)
  for levels in [0, -1, 101]:
    with pytest.raises(ValueError):
      await market.depth(levels=levels)
  assert request.await_count == 1


@pytest.mark.parametrize('perp,cap', [(False, 1500), (True, 200)])
async def test_sparse_candle_pages_retry_only_failed_window_and_keep_bounds(
  perp: bool, cap: int
):
  """Empty pages never stop time paging; the successful first page is not replayed."""
  boundary = NOW + timedelta(minutes=cap)
  last = boundary + timedelta(minutes=cap)

  def row(time: datetime):
    """Different spot/futures OHLC layouts with real volume-unit differences."""
    return (
      (time, 10.0, 12.0, 8.0, 11.0, 20.0, 220.0)
      if perp
      else (time, D(10), D(11), D(12), D(8), D(2), D(22))
    )

  request = AsyncMock(
    side_effect=[
      [row(NOW - timedelta(minutes=1)), row(NOW), row(boundary)],
      TypedNetworkError('transient'),
      [],
      [row(last), row(last + timedelta(minutes=1))],
    ]
  )
  shared = shared_client(
    spot=SimpleNamespace(klines=request), futures=SimpleNamespace(klines=request)
  )
  market = (
    LinearPerpMarket(shared=shared, symbol='XBTUSDTM', contract_multiplier=D('.001'))
    if perp
    else SpotMarket(shared=shared, symbol='BTC-USDT')
  )
  with Context().retried(NetworkError, max_retries=1, base_delay=0).use():
    candles = await market.candles('1m', NOW, last + timedelta(minutes=1))
  assert [c.time for c in candles] == [NOW, last]
  assert (
    candles[0].open == 10
    and candles[0].high == 12
    and candles[0].low == 8
    and candles[0].close == 11
  )
  assert candles[0].volume == (D('.020') if perp else D(2))
  assert request.await_count == 4
  key = 'from_' if perp else 'start_at'
  assert [c.kwargs[key] for c in request.await_args_list] == [
    NOW,
    boundary,
    boundary,
    last,
  ]


@pytest.mark.parametrize('perp', [False, True])
async def test_fractional_candle_bounds_preserve_last_valid_open(perp: bool):
  """An end just after a candle open includes that row at wire timestamp precision."""
  request = AsyncMock(return_value=[])
  shared = shared_client(
    spot=SimpleNamespace(klines=request), futures=SimpleNamespace(klines=request)
  )
  market = (
    LinearPerpMarket(shared=shared, symbol='XBTUSDTM', contract_multiplier=D('.001'))
    if perp
    else SpotMarket(shared=shared, symbol='BTC-USDT')
  )
  end = NOW + timedelta(minutes=1, microseconds=500)
  await market.candles('1m', NOW + timedelta(microseconds=500), end)
  assert request.await_args is not None
  upper = request.await_args.kwargs['to' if perp else 'end_at']
  assert upper == NOW + timedelta(minutes=1)
  assert await market.candles('1m', NOW, NOW) == []
  assert request.await_count == 1
  with pytest.raises(ValueError):
    market.candles('1m', NOW.replace(tzinfo=None), NOW)
  with pytest.raises(ValueError):
    market.candles(cast(CandleInterval, '3m'), NOW, end)


async def test_funding_open_start_paging_and_inclusive_boundaries():
  """Use the typed pager, remove its overlapping boundary and preserve open start."""
  request = AsyncMock(
    side_effect=[
      [
        {
          'symbol': 'XBTUSDTM',
          'fundingRate': 0.0001,
          'timepoint': NOW - timedelta(hours=i),
        }
        for i in range(100)
      ],
      [
        {
          'symbol': 'XBTUSDTM',
          'fundingRate': 0.0002,
          'timepoint': NOW - timedelta(hours=i),
        }
        for i in [99, 100]
      ],
    ]
  )
  fees = cast(PublicFundingHistory, SimpleNamespace(public_funding_history=request))

  class FundingClient:
    """Reuse the real typed pager over a mocked page transport."""

    def public_funding_history_paged(
      self, symbol: str, *, from_: datetime, to: datetime
    ):
      """Preserve the generated pager's exact overlap and continuation behavior."""
      return PublicFundingHistory.public_funding_history_paged(
        fees, symbol, from_=from_, to=to
      )

  api = SimpleNamespace(funding_fees=FundingClient())

  market = LinearPerpMarket(
    shared=shared_client(futures=api), symbol='XBTUSDTM', contract_multiplier=D('.001')
  )
  rows = await market.funding_rates(end=NOW)
  assert len(rows) == len({r.time for r in rows}) == 101
  assert rows[0].time == NOW
  assert request.await_args_list[0].kwargs['from_'] == datetime(
    1970, 1, 1, tzinfo=timezone.utc
  )
  assert request.await_args_list[1].kwargs['to'] == NOW - timedelta(hours=99)


async def test_stream_fans_out_once_and_unsubscribes_after_last_reader():
  """Two market objects share one upstream and receive independent Book objects."""
  queue: asyncio.Queue[dict[str, list[tuple[Decimal, int]]]] = asyncio.Queue()

  async def iterate() -> AsyncIterator[dict[str, list[tuple[Decimal, int]]]]:
    """Keep the fake upstream open until subscribers leave."""
    while True:
      yield await queue.get()

  class Stream:
    """Minimal native stream with observable cleanup."""

    unsubscribe = AsyncMock()

    def __aiter__(self):
      """Return the shared queue iterator."""
      return iterate()

  connect = AsyncMock(return_value=Stream())
  shared = shared_client(
    streams=SimpleNamespace(futures_public=SimpleNamespace(orderbook_level5=connect))
  )
  a = LinearPerpMarket(shared=shared, symbol='XBTUSDTM', contract_multiplier=D('.001'))
  b = LinearPerpMarket(shared=shared, symbol='XBTUSDTM', contract_multiplier=D('.001'))
  async with a.depth_stream() as first:
    async with b.depth_stream(levels=1) as second:
      queue.put_nowait({'bids': [(D(99), 2)], 'asks': [(D(101), 3)]})
      x, y = await asyncio.wait_for(
        asyncio.gather(anext(aiter(first)), anext(aiter(second))), 1
      )
      assert x is not y
      assert x.bids[0].qty == y.bids[0].qty == D('.002')
      assert connect.await_count == 1
    Stream.unsubscribe.assert_not_called()
  Stream.unsubscribe.assert_awaited_once()


async def test_market_sdk_constructs_public_kucoin_without_credentials(
  monkeypatch: pytest.MonkeyPatch,
):
  """The router installs a genuine public default and never resolves private keys."""
  monkeypatch.delenv('KUCOIN_API_KEY', raising=False)
  monkeypatch.delenv('KUCOIN_API_SECRET', raising=False)
  monkeypatch.delenv('KUCOIN_API_PASSPHRASE', raising=False)
  sdk = MarketSDK()
  assert sdk.all_accounts['kucoin'].public
  venue = await sdk.venue('kucoin')
  assert isinstance(venue, KucoinMarket)
