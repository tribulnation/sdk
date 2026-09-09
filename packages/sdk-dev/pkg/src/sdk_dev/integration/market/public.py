"""Read-only market checks; account-derived fees require a configured private account."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit
import asyncio

import pytest
from typing_extensions import cast
from sdk_dev.narrow import is_mapping

from tribulnation.sdk import Context, MarketSDK, NetworkError, RateLimited
from tribulnation.sdk.market import (
  Book,
  FundingRate,
  Market,
  NextFunding,
  PerpMarket,
  PerpExchange,
  PerpStats,
  Rules,
  Ticker,
)
from ..accounts import (
  package_of,
  require_credentials,
  selected_accounts,
  surface_support,
)
from ..support import describe_exception
from ..runtime import loop_of
from .conftest import market_sdk
from .support import CASES, END

MARKETS = {
  **{venue: [case.market_id for case in cases] for venue, cases in CASES.items()},
}
READS = (
  'exchanges',
  'markets',
  'depth',
  'depth_stream',
  'rules',
  'tickers',
  'index',
  'next_funding',
  'funding_rates',
  'perp_stats',
)
TIMEOUT = 30
AUTHENTICATED_READS: dict[str, frozenset[str]] = {
  'binance': frozenset({'rules'}),
  'bybit': frozenset({'rules'}),
  'dydx': frozenset({'rules'}),
  'hyperliquid': frozenset({'rules'}),
  'coinbase': frozenset(
    {'markets', 'rules', 'tickers', 'index', 'next_funding', 'perp_stats'}
  ),
}
"""Current SDK paths, not upstream capabilities: rules fetch user fee tiers;
Coinbase catalogue/funding paths still use authenticated Advanced Trade products.
Do not infer this from a caught AuthError: an unexpected rejection stays a failure.
"""


def needs_account(venue: str, method: str, *, public: bool) -> bool:
  """Whether this account-derived read lacks a configured private account."""
  return public and method in AUTHENTICATED_READS.get(venue, frozenset())


@dataclass
class PublicResults:
  """Independent read outcomes, with explicit gaps separate from failures."""

  values: dict[str, object] = field(default_factory=dict[str, object])
  failures: dict[str, str] = field(default_factory=dict[str, str])
  skips: dict[str, str] = field(default_factory=dict[str, str])

  async def attempt(self, name: str, call: Callable[[], Awaitable[object]]):
    """Bound each read, retaining failures without hiding subsequent checks."""
    try:
      with Context().retried(NetworkError, RateLimited, max_retries=2).use():
        self.values[name] = await asyncio.wait_for(call(), TIMEOUT)
    except Exception as exception:
      self.failures[name] = describe_exception(exception)


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Cover declared market implementations, including custom account aliases."""
  if 'public_market' not in metafunc.fixturenames:
    return
  sdk = market_sdk(metafunc.config)
  ids = [
    f'{account}:{market}'
    for account in selected_accounts(
      metafunc.config, sdk.all_accounts, surface='market'
    )
    for market in MARKETS.get(package_of(sdk.all_accounts[account].venue), [])
  ]
  metafunc.parametrize('public_market', ids, ids=ids, scope='module')


async def first_book(market: Market) -> Book:
  """Read one public stream item and leave the subscription before root cleanup."""
  async with market.depth_stream() as stream:
    async for book in stream:
      return book
  raise RuntimeError('Order book stream ended before its first item')


async def funding_rates(market: PerpMarket) -> Sequence[FundingRate]:
  """Read a bounded funding window without assuming response ordering."""
  return await market.funding_rates(END - timedelta(days=3), END)


async def collect_public(sdk: MarketSDK, id: str) -> PublicResults:
  """Acquire one managed venue and call only a fixed allowlist of market-data reads."""
  result = PublicResults()
  account_id, exchange_id, symbol = id.split(':', 2)
  venue_slug = package_of(sdk.all_accounts[account_id].venue)
  support = surface_support('market')[venue_slug]
  try:
    async with sdk:
      venue = await sdk.venue(account_id)
      exchange = await venue.exchange(exchange_id)
      market = await exchange.market(symbol)
      calls: dict[str, Callable[[], Awaitable[object]]] = {
        'exchanges': venue.exchanges,
        'markets': exchange.markets,
        'depth': market.depth,
        'depth_stream': lambda: first_book(market),
        'rules': market.rules,
        'tickers': lambda: exchange.tickers([symbol]),
      }
      if isinstance(market, PerpMarket):
        calls.update(
          {
            'index': market.index,
            'next_funding': market.next_funding,
            'funding_rates': lambda: funding_rates(market),
          }
        )
      if isinstance(exchange, PerpExchange):
        calls['perp_stats'] = lambda: exchange.perp_stats([symbol])
      for name in READS:
        if name not in calls:
          result.skips[name] = 'Perpetual-only method on a spot market'
        elif (
          name not in ('markets', 'exchanges')
          and support.support == 'partial'
          and support.methods is not None
          and name not in support.methods
        ):
          result.skips[name] = f'{name} is not declared in impl.toml'
        elif venue_slug == 'binance' and exchange_id == 'usdm' and name == 'rules':
          result.skips[name] = 'USD-M rules are explicitly unsupported (impl.toml note)'
        elif (
          venue_slug == 'mexc'
          and exchange_id == 'perp'
          and name in ('rules', 'depth_stream')
        ):
          result.skips[name] = (
            'MEXC perpetual rules/streams are explicitly unsupported (impl.toml note)'
          )
        elif needs_account(
          venue_slug, name, public=sdk.all_accounts[account_id].public
        ):
          result.skips[name] = (
            'Current SDK path requires a configured private account (fee tier or catalogue)'
          )
        else:
          await result.attempt(name, calls[name])
  except Exception as exception:
    failure = describe_exception(exception)
    for name in READS:
      result.failures[name] = failure
  return result


@pytest.fixture(scope='module')
def public_result(public_market: str, pytestconfig: pytest.Config) -> PublicResults:
  """Collect all public reads once per account and reference market."""
  sdk = market_sdk(pytestconfig)
  require_credentials(sdk.all_accounts[public_market.split(':', 1)[0]])
  return loop_of(pytestconfig).run_until_complete(collect_public(sdk, public_market))


def check_book(value: object):
  """Validate the book representation without imposing venue-specific depth sizes."""
  assert isinstance(value, Book)
  for side in (value.bids, value.asks):
    for entry in side:
      assert isinstance(entry.price, Decimal) and entry.price.is_finite()
      assert isinstance(entry.qty, Decimal) and entry.qty.is_finite()
      assert entry.price > 0 and entry.qty >= 0
  assert [entry.price for entry in value.bids] == sorted(
    (entry.price for entry in value.bids), reverse=True
  )
  assert [entry.price for entry in value.asks] == sorted(
    entry.price for entry in value.asks
  )


@pytest.mark.parametrize('method', READS)
def test_public_read(public_result: PublicResults, public_market: str, method: str):
  """Validate only public contracts; unsupported methods remain visible skips."""
  if method in public_result.failures:
    pytest.fail(public_result.failures[method], pytrace=False)
  if method in public_result.skips:
    pytest.skip(public_result.skips[method])
  value = public_result.values[method]
  symbol = public_market.split(':', 2)[2]
  if method == 'exchanges':
    assert isinstance(value, Sequence) and not isinstance(value, str)
    ids: set[str] = set()
    for description in cast(Sequence[object], value):
      assert is_mapping(description)
      identifier = description.get('id')
      name = description.get('name')
      assert isinstance(identifier, str) and identifier not in ids
      ids.add(identifier)
      assert isinstance(name, str) and name.strip()
      assert description.get('type') in ('spot', 'perp')
      if 'url' in description:
        url = description['url']
        assert isinstance(url, str)
        parsed = urlsplit(url)
        assert parsed.scheme == 'https' and parsed.hostname
    assert public_market.split(':', 2)[1] in ids
  elif method == 'markets':
    assert isinstance(value, Sequence) and not isinstance(value, str)
    assert symbol in value
  elif method in ('depth', 'depth_stream'):
    check_book(value)
  elif method == 'rules':
    assert isinstance(value, Rules)
    assert value.base and value.quote
    assert value.tick_size.is_finite() and value.tick_size > 0
    assert value.step_size.is_finite() and value.step_size > 0
  elif method == 'tickers':
    assert is_mapping(value)
    assert symbol in value and isinstance(value[symbol], Ticker)
    assert set(value) <= {symbol}
  elif method == 'index':
    assert isinstance(value, Decimal) and value.is_finite() and value > 0
  elif method == 'next_funding':
    assert isinstance(value, NextFunding)
    assert value.time.utcoffset() is not None
    assert value.rate.is_finite() and value.interval > timedelta(0)
  elif method == 'funding_rates':
    assert isinstance(value, Sequence)
    for rate in cast(Sequence[object], value):
      assert isinstance(rate, FundingRate)
      assert rate.time.utcoffset() is not None and rate.rate.is_finite()
      assert END - timedelta(days=3) <= rate.time <= END
  elif method == 'perp_stats':
    assert is_mapping(value)
    assert set(value) == {symbol}
    stats = value[symbol]
    assert isinstance(stats, PerpStats)
    assert stats.index.is_finite() and stats.index > 0
    for optional in (stats.mark, stats.funding, stats.open_interest):
      assert optional is None or isinstance(optional, Decimal) and optional.is_finite()
    assert stats.open_interest is None or stats.open_interest >= 0
    assert (
      stats.next_funding_time is None or stats.next_funding_time.utcoffset() is not None
    )
    assert stats.funding_interval is None or stats.funding_interval > timedelta(0)
