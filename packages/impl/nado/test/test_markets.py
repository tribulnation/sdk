"""Rules, depth and its diff stream, candles, tickers, perpetual stats and funding."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from typing_extensions import Any, AsyncIterator
from typed_core.util import Stream

from tribulnation.nado.core import Shared
from tribulnation.nado.market.markets import NadoPerpMarket, NadoSpotMarket
from tribulnation.nado.market.stats import next_hour
from tribulnation.sdk import NetworkError
from tribulnation.sdk.market import Book

from .conftest import X18

T0 = datetime(2026, 11, 17, 10, 27, 40, tzinfo=timezone.utc)


def btc(shared: Shared) -> NadoPerpMarket:
  """BTC-PERP over `shared`."""
  return NadoPerpMarket(shared=shared, symbol='BTC-PERP', product_id=2)


def at(ms: int) -> datetime:
  """`T0` plus `ms` milliseconds."""
  return T0 + timedelta(milliseconds=ms)


def levels(*rows: tuple[int, str]) -> list[tuple[int, int]]:
  """Venue levels from `(price, size)`."""
  return [(price * X18, int(Decimal(size) * X18)) for price, size in rows]


async def test_rules_and_spot_assets(shared: Shared):
  """Ticks, steps and the minimum notional are x18; spot rules name USDT0 as quote."""
  r = await btc(shared).rules()
  assert (r.tick_size, r.step_size, r.min_value, r.fee_asset, r.api) == (
    Decimal(1),
    Decimal('0.00005'),
    Decimal(100),
    'USDT0',
    True,
  )
  assert r.fees is not None and r.fees.taker_buy == Decimal('0.00035')
  s = await NadoSpotMarket(shared=shared, symbol='KBTC', product_id=1).rules()
  assert (s.base, s.quote) == ('KBTC', 'USDT0')


async def test_untradable_markets_are_not_api_tradable(shared: Shared):
  """Only `live` markets take every order type."""
  shared.symbols['BTC-PERP']['trading_status'] = 'reduce_only'
  assert not (await btc(shared).rules()).api


async def test_depth_stream_applies_diffs_past_the_snapshot(shared: Shared, fake: Any):
  """Diffs already in the snapshot are skipped, later ones applied (0 deletes), and a
  diff that does not chain onto the last one ends the stream."""
  diffs: list[Any] = [
    {
      'min_timestamp': at(-20),
      'max_timestamp': at(-10),
      'last_max_timestamp': at(-30),
      'bids': levels((99, '5')),
      'asks': [],
    },
    {
      'min_timestamp': at(5),
      'max_timestamp': at(10),
      'last_max_timestamp': at(-10),
      'bids': levels((100, '0'), (98, '2')),
      'asks': levels((102, '3')),
    },
    {
      'min_timestamp': at(50),
      'max_timestamp': at(60),
      'last_max_timestamp': at(30),
      'bids': [],
      'asks': [],
    },
  ]

  async def pushed() -> AsyncIterator[Any]:
    for d in diffs:
      yield d

  async def unsubscribe():
    pass

  async def book_depth(product_id: int) -> Stream[Any, Any, Any]:
    assert product_id == 2
    return Stream(reply=None, stream=pushed(), unsubscribe=unsubscribe)

  async def market_liquidity(*, product_id: int, depth: int) -> Any:
    assert (product_id, depth) == (2, 100)
    return {
      'bids': levels((100, '1'), (99, '2')),
      'asks': levels((101, '1')),
      'timestamp': T0,
      'product_id': 2,
    }

  fake.streams.book_depth = book_depth
  fake.gateway.market_liquidity = market_liquidity
  seen: list[Book] = []
  with pytest.raises(NetworkError):
    async with btc(shared).depth_stream(queue_size=10, overflow='fail') as stream:
      async for book in stream:
        seen.append(book)
  assert [(e.price, e.qty) for e in seen[0].bids] == [(100, 1), (99, 2)]
  assert [(e.price, e.qty) for e in seen[1].bids] == [(99, 2), (98, 2)]
  assert [(e.price, e.qty) for e in seen[1].asks] == [(101, 1), (102, 3)]
  assert seen[1].time == at(10) and len(seen) == 2


async def test_candles_stop_before_start(shared: Shared, fake: Any):
  """Newest first from `max_time`; the exclusive end and the start are applied."""
  hour = timedelta(hours=1)

  def candle(t: datetime) -> Any:
    return {
      'product_id': 2,
      'granularity': 3600,
      'submission_idx': 1,
      'timestamp': t,
      'open_x18': X18,
      'high_x18': 2 * X18,
      'low_x18': X18,
      'close_x18': X18,
      'volume': 3 * X18,
    }

  class Pager:
    def via(self, call: Any) -> Any:
      async def pages() -> AsyncIterator[list[Any]]:
        yield [candle(T0), candle(T0 - hour)]
        yield [candle(T0 - 2 * hour), candle(T0 - 3 * hour)]
        raise AssertionError('walked past start')

      return pages()

  def candlesticks_paged(**kwargs: Any) -> Any:
    assert kwargs['granularity'] == 3600 and kwargs['max_time'] == T0
    return Pager()

  fake.archive.candlesticks_paged = candlesticks_paged
  rows = await btc(shared).candles('1h', T0 - 2 * hour, T0)
  assert [c.time for c in rows] == [T0 - hour, T0 - 2 * hour]
  assert rows[0].volume == 3 and rows[0].quote_volume is None


async def test_next_funding_is_per_hourly_settlement(shared: Shared, fake: Any):
  """The venue's 24-hour rate and premium over 24, settling on the next hour."""

  async def funding_rate(product_id: int) -> Any:
    return {
      'product_id': 2,
      'funding_rate_x18': 24 * 10**12,
      'update_time': T0,
      'premium_x18': -48 * 10**12,
    }

  fake.archive.funding_rate = funding_rate
  f = await btc(shared).next_funding()
  assert (f.rate, f.premium, f.interval) == (
    Decimal('0.000001'),
    Decimal('-0.000002'),
    timedelta(hours=1),
  )
  assert f.time == datetime(2026, 11, 17, 11, tzinfo=timezone.utc)
  assert next_hour(datetime(2026, 11, 17, 11, tzinfo=timezone.utc)).hour == 12


async def test_tickers_join_the_archive_and_the_gateway(shared: Shared, fake: Any):
  """Last price and volumes from the archive (floats, read back as sent), best levels
  from the gateway; an empty side is `None`."""

  async def tickers(market: str) -> Any:
    assert market == 'perp'
    return {
      'BTC-PERP_USDT0': {
        'product_id': 2,
        'last_price': 64304.1,
        'base_volume': 3277.38125,
        'quote_volume': 2.5,
      }
    }

  async def market_prices(ids: list[int]) -> Any:
    assert sorted(ids) == [2, 4]
    return {'market_prices': [{'product_id': 2, 'bid_x18': 64243 * X18, 'ask_x18': 0}]}

  fake.archive_v2.tickers = tickers
  fake.gateway.market_prices = market_prices
  from tribulnation.nado.market.exchanges import NadoPerpExchange

  out = await NadoPerpExchange(shared=shared).tickers()
  t = out['BTC-PERP']
  assert (t.last, t.bid, t.ask, t.base_volume_24h) == (
    Decimal('64304.1'),
    Decimal(64243),
    None,
    Decimal('3277.38125'),
  )
  assert out['ETH-PERP'].last is None
