"""Venue rows mapped onto SDK markets, rules, stats, collateral and positions."""

from datetime import datetime, timezone
from decimal import Decimal

from typing_extensions import Any

import pytest
from typed_core import PaginatedResponse

from tribulnation.extended import ExtendedMarket
from tribulnation.extended.market import ExtendedPerpExchange
from tribulnation.extended.market.account import bucket
from tribulnation.sdk.market import ExchangeFundingPayment

NEXT = datetime(2026, 10, 22, 13, tzinfo=timezone.utc)


def stats(**overrides: Any) -> dict[str, Any]:
  """A market's live statistics."""
  out: dict[str, Any] = {
    'dailyVolume': Decimal('190002657.46'),
    'dailyVolumeBase': Decimal('2266.86'),
    'dailyPriceChange': Decimal(0),
    'dailyPriceChangePercentage': Decimal(0),
    'dailyLow': Decimal(0),
    'dailyHigh': Decimal(0),
    'lastPrice': Decimal('81800'),
    'askPrice': Decimal('81801'),
    'bidPrice': Decimal('81800'),
    'markPrice': Decimal('81799.5'),
    'indexPrice': Decimal('81790'),
    'fundingRate': Decimal('0.000013'),
    'nextFundingRate': NEXT,
    'openInterest': Decimal('1000000'),
    'openInterestBase': Decimal('12.5'),
  }
  return {**out, **overrides}


def market(
  name: str, *, kind: str = 'PERPETUAL', status: str = 'ACTIVE', **s: Any
) -> Any:
  """A market row."""
  return {
    'name': name,
    'type': kind,
    'status': status,
    'isRfq': False,
    'assetName': name.split('-')[0],
    'collateralAssetName': 'USD',
    'marketStats': stats(**s),
    'tradingConfig': {
      'minOrderSize': Decimal('0.0001'),
      'minOrderSizeChange': Decimal('0.00001'),
      'minPriceChange': Decimal('1'),
      'maxMarketOrderValue': Decimal('3000000'),
      'maxLimitOrderValue': Decimal('15000000'),
      'maxPositionValue': Decimal('60000000'),
      'maxLeverage': Decimal('50'),
      'maxNumOrders': 200,
      'limitPriceCap': Decimal('0.05'),
      'limitPriceFloor': Decimal('0.04'),
    },
  }


MARKETS = [
  market('BTC-USD'),
  market('MKR-USD', status='REDUCE_ONLY', bidPrice=Decimal(0), askPrice=Decimal(0)),
  market('NEW-USD', status='PRELISTED'),
  market('OLD-USD', status='DELISTED'),
  market('BTCSPOT-USD', kind='SPOT'),
]


@pytest.fixture
async def exchange():
  """The perpetual exchange of a public venue, with `info.markets` served locally."""
  async with ExtendedMarket.new(public=True) as venue:

    async def markets(names: list[str] | None = None) -> list[Any]:
      """Every fixture market, or the named ones."""
      return [m for m in MARKETS if names is None or m['name'] in names]

    venue.shared.client.info.markets = markets  # type: ignore[method-assign]
    yield await venue.perp_exchange('perp')


async def test_markets_list_listed_perpetuals(exchange: ExtendedPerpExchange):
  """Spot and delisted markets are not listed; a delisted perpetual still resolves."""
  assert await exchange.markets() == ['BTC-USD', 'MKR-USD', 'NEW-USD']
  assert (await exchange.market('OLD-USD')).id == 'extended:perp:OLD-USD'
  with pytest.raises(ValueError):
    await exchange.market('BTCSPOT-USD')


async def test_tickers_map_zero_prices_to_none(exchange: ExtendedPerpExchange):
  """A `0` best price is the venue's "none"; volumes are base and collateral units."""
  tickers = await exchange.tickers(['BTC-USD', 'MKR-USD', 'OLD-USD', 'nope'])
  assert list(tickers) == ['BTC-USD', 'MKR-USD']
  btc, mkr = tickers['BTC-USD'], tickers['MKR-USD']
  assert (btc.bid, btc.ask, btc.bid_qty) == (Decimal('81800'), Decimal('81801'), None)
  assert btc.quote_volume_24h == Decimal('190002657.46')
  assert (mkr.bid, mkr.ask) == (None, None)
  assert await exchange.tickers([]) == {}


async def test_perp_stats_and_next_funding(exchange: ExtendedPerpExchange):
  """Index, mark, the hourly funding estimate and base-unit open interest."""
  (s,) = (await exchange.perp_stats(['BTC-USD'])).values()
  assert (s.index, s.mark, s.funding, s.next_funding_time, s.open_interest) == (
    Decimal('81790'),
    Decimal('81799.5'),
    Decimal('0.000013'),
    NEXT,
    Decimal('12.5'),
  )
  funding = await exchange.next_funding('BTC-USD')
  assert (funding.rate, funding.time, funding.interval.total_seconds()) == (
    Decimal('0.000013'),
    NEXT,
    3600,
  )
  assert await exchange.index('BTC-USD') == Decimal('81790')


async def test_rules_carry_the_side_specific_band(exchange: ExtendedPerpExchange):
  """Tick, step, minimum size, the band against mark, no standard fees, `api` on
  `ACTIVE` only."""
  rules = await exchange.rules('BTC-USD')
  assert (rules.tick_size, rules.step_size, rules.fixed_min_qty) == (
    Decimal('1'),
    Decimal('0.00001'),
    Decimal('0.0001'),
  )
  assert (rules.rel_min_price, rules.rel_max_price) == (
    Decimal('0.96'),
    Decimal('1.05'),
  )
  assert (rules.fee_asset, rules.fees, rules.api) == ('USD', None, True)
  assert not (await exchange.rules('MKR-USD')).api


async def test_account_reads(exchange: ExtendedPerpExchange):
  """Fees, leverage (cached), the signed position and the one cross bucket."""
  account = exchange.shared.client.account
  calls: list[str] = []

  async def fees(markets: list[str]) -> list[Any]:
    """The account's rates."""
    return [
      {
        'market': 'BTC-USD',
        'makerFeeRate': Decimal('0'),
        'takerFeeRate': Decimal('0.00025'),
        'builderFeeRate': Decimal('0'),
      }
    ]

  async def leverage(markets: list[str]) -> list[Any]:
    """The account's leverage setting."""
    calls.append('leverage')
    return [{'market': 'BTC-USD', 'leverage': Decimal('10')}]

  async def positions(markets: list[str]) -> list[Any]:
    """One short position."""
    return [
      {
        'market': 'BTC-USD',
        'side': 'SHORT',
        'size': Decimal('0.5'),
        'openPrice': Decimal('80000'),
      }
    ]

  async def balance() -> Any:
    """A funded balance."""
    return {
      'equity': Decimal('1000'),
      'availableForTrade': Decimal('800'),
      'initialMargin': Decimal('200'),
      'marginRatio': Decimal('0.05'),
      'leverage': Decimal('2'),
    }

  account.fees = fees  # type: ignore[method-assign]
  account.leverage = leverage  # type: ignore[method-assign]
  account.positions = positions  # type: ignore[method-assign]
  account.balance = balance  # type: ignore[method-assign]
  rates = await exchange.fees('BTC-USD')
  assert (rates.maker_buy, rates.taker_sell) == (Decimal('0'), Decimal('0.00025'))
  assert await exchange.leverage('BTC-USD') == Decimal('10')
  assert await exchange.leverage('BTC-USD') == Decimal('10')
  assert calls == ['leverage']
  position = await exchange.perp_position('BTC-USD')
  assert (position.size, position.entry_price) == (Decimal('-0.5'), Decimal('80000'))
  collateral = await exchange.perp_collateral()
  assert collateral == await exchange.perp_collateral('BTC-USD')
  assert (collateral.maintenance_margin, collateral.margin_mode) == (
    Decimal('50'),
    'cross',
  )
  assert await exchange.available_notional('BTC-USD') == Decimal('8000')


def test_no_balance_is_an_empty_bucket():
  """The venue's zero balance (`None` from the client) is all zeros, not an error."""
  empty = bucket(None)
  assert (empty.equity, empty.free_collateral, empty.leverage) == (0, 0, 0)


async def test_funding_payments_per_market_and_exchange_wide(
  exchange: ExtendedPerpExchange,
):
  """A market's payments ask for that market; the exchange-wide form asks for every
  market; an unknown market raises before any request."""
  start = datetime(2026, 10, 1, tzinfo=timezone.utc)
  asked: list[Any] = []
  row: dict[str, Any] = {
    'id': 1,
    'accountId': 3880,
    'market': 'BTC-USD',
    'positionId': 7,
    'side': 'LONG',
    'value': Decimal('3.07'),
    'markPrice': Decimal('81799.5'),
    'fundingFee': Decimal('-0.000041'),
    'fundingRate': Decimal('0.000013'),
    'paidTime': NEXT,
  }

  def funding_history_paged(market: Any = None, **kwargs: Any) -> Any:
    """One page holding one payment."""
    asked.append(market)

    async def fetch(state: int) -> tuple[list[Any], None]:
      return [row], None

    return PaginatedResponse(0, fetch)

  exchange.shared.client.account.funding_history_paged = funding_history_paged  # type: ignore[method-assign]
  (one,) = await exchange.funding_payments('BTC-USD', start, NEXT)
  (every,) = await exchange.funding_payments(None, start, NEXT)
  market = await exchange.market('BTC-USD')
  (direct,) = await market.funding_payments(start, NEXT)
  assert asked == [['BTC-USD'], None, ['BTC-USD']]
  assert one.amount == direct.amount == Decimal('-0.000041')
  assert isinstance(every, ExchangeFundingPayment) and every.market_id == 'BTC-USD'
  with pytest.raises(ValueError):
    await exchange.funding_payments('XYZ-USD', start, NEXT)


async def test_venue_ids_follow_the_network():
  """Testnet objects report `extended_testnet`; the market id names the account."""
  async with ExtendedMarket.new(
    network='testnet', public=True, account_id='x'
  ) as venue:
    assert venue.venue_id == 'extended_testnet'
    assert [e['id'] for e in await venue.exchanges()] == ['perp']
    with pytest.raises(ValueError):
      await venue.exchange('spot')
