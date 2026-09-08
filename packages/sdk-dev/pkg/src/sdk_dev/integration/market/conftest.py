"""Pytest fixtures for live market integration tests."""

from collections.abc import Sequence
import asyncio

import pytest
from typing_extensions import cast

from tribulnation.sdk import Context, MarketSDK, NetworkError, RateLimited
from tribulnation.sdk.market import Candle
from ..support import describe_exception
from .support import (
  CASES,
  HOUR,
  START,
  STRADDLE_EXTRA,
  WINDOW,
  CandleCase,
  CandlesResult,
)

SDK: pytest.StashKey[MarketSDK] = pytest.StashKey()


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Parameterize tests over every configured account with a candle case."""
  if 'candle_market' not in metafunc.fixturenames:
    return

  sdk = metafunc.config.stash.get(SDK, None)
  if sdk is None:
    accounts = cast(str, metafunc.config.getoption('accounts_config'))
    sdk = MarketSDK.load(accounts)
    metafunc.config.stash[SDK] = sdk
  markets = [
    f'{account}:{case.market_id}'
    for account, entry in sdk.all_accounts.items()
    for case in CASES.get(entry.venue, [])
  ]
  metafunc.parametrize('candle_market', markets, ids=markets, scope='module')


def case_of(sdk: MarketSDK, market: str) -> CandleCase:
  """The case a parametrized market id was built from."""
  account, market_id = market.split(':', 1)
  venue = sdk.all_accounts[account].venue
  return next(case for case in CASES[venue] if case.market_id == market_id)


async def fetch_candles(
  sdk: MarketSDK, market: str, *, count: int
) -> Sequence[Sequence[Candle]]:
  """Fetch `count` hourly candles from `START`, page by page, retrying transient failures."""
  with Context().retried(NetworkError, RateLimited, max_retries=5).use():
    async with sdk:
      end = START + count * HOUR
      return [page async for page in sdk.candles(market, '1h', START, end)]


def result_of(sdk: MarketSDK, market: str, *, count: int) -> CandlesResult:
  """Fetch one market's candles, describing rather than raising a failure."""
  try:
    pages = asyncio.run(fetch_candles(sdk, market, count=count))
  except Exception as exception:
    return CandlesResult(failure=describe_exception(exception))
  return CandlesResult(pages=pages)


@pytest.fixture(scope='module')
def candle_case(candle_market: str, pytestconfig: pytest.Config) -> CandleCase:
  """The case behind the parametrized market."""
  return case_of(pytestconfig.stash[SDK], candle_market)


@pytest.fixture(scope='module')
def window_result(candle_market: str, pytestconfig: pytest.Config) -> CandlesResult:
  """Three days of hourly candles, fetched once per market for the module."""
  return result_of(pytestconfig.stash[SDK], candle_market, count=WINDOW)


@pytest.fixture(scope='module')
def straddle_result(
  candle_market: str, candle_case: CandleCase, pytestconfig: pytest.Config
) -> CandlesResult:
  """One page plus `STRADDLE_EXTRA` hourly candles, fetched once per market."""
  count = candle_case.page + STRADDLE_EXTRA
  return result_of(pytestconfig.stash[SDK], candle_market, count=count)
