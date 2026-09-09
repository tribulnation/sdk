"""Pytest fixtures for live market integration tests."""

from collections.abc import Sequence

import pytest

from tribulnation.sdk import Context, MarketSDK, NetworkError, RateLimited
from tribulnation.sdk.market import Candle
from ..support import describe_exception
from ..runtime import loop_of
from ..accounts import load_accounts, selected_accounts, require_credentials, package_of
from .support import (
  CASES,
  HOUR,
  END,
  STRADDLE_EXTRA,
  WINDOW,
  CandleCase,
  CandlesResult,
)

SDK: pytest.StashKey[MarketSDK] = pytest.StashKey()


def market_sdk(config: pytest.Config) -> MarketSDK:
  """Share account configuration while each read owns a fresh venue lifetime."""
  sdk = config.stash.get(SDK, None)
  if sdk is None:
    sdk = MarketSDK(accounts=load_accounts(config))
    config.stash[SDK] = sdk
  return sdk


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Parameterize tests over every configured account with a candle case."""
  if 'candle_market' not in metafunc.fixturenames:
    return

  sdk = market_sdk(metafunc.config)
  markets = [
    f'{account}:{case.market_id}'
    for account in selected_accounts(
      metafunc.config, sdk.all_accounts, surface='market'
    )
    for case in CASES.get(package_of(sdk.all_accounts[account].venue), [])
  ]
  metafunc.parametrize('candle_market', markets, ids=markets, scope='module')


def case_of(sdk: MarketSDK, market: str) -> CandleCase:
  """The case a parametrized market id was built from."""
  account, market_id = market.split(':', 1)
  venue = package_of(sdk.all_accounts[account].venue)
  return next(case for case in CASES[venue] if case.market_id == market_id)


async def fetch_candles(
  sdk: MarketSDK, market: str, *, count: int
) -> Sequence[Sequence[Candle]]:
  """Fetch recent closed hourly candles, retrying transient failures."""
  with Context().retried(NetworkError, RateLimited, max_retries=5).use():
    async with sdk:
      return [page async for page in sdk.candles(market, '1h', END - count * HOUR, END)]


def result_of(
  config: pytest.Config, sdk: MarketSDK, market: str, *, count: int
) -> CandlesResult:
  """Fetch one market's candles, describing rather than raising a failure."""
  require_credentials(sdk.all_accounts[market.split(':', 1)[0]])
  try:
    pages = loop_of(config).run_until_complete(fetch_candles(sdk, market, count=count))
  except Exception as exception:
    return CandlesResult(failure=describe_exception(exception))
  return CandlesResult(pages=pages, start=END - count * HOUR, end=END)


@pytest.fixture(scope='module')
def candle_case(candle_market: str, pytestconfig: pytest.Config) -> CandleCase:
  """The case behind the parametrized market."""
  return case_of(pytestconfig.stash[SDK], candle_market)


@pytest.fixture(scope='module')
def window_result(candle_market: str, pytestconfig: pytest.Config) -> CandlesResult:
  """Three days of hourly candles, fetched once per market for the module."""
  return result_of(pytestconfig, pytestconfig.stash[SDK], candle_market, count=WINDOW)


@pytest.fixture(scope='module')
def straddle_result(
  candle_market: str, candle_case: CandleCase, pytestconfig: pytest.Config
) -> CandlesResult:
  """One page plus `STRADDLE_EXTRA` hourly candles, fetched once per market."""
  if candle_case.page is None:
    pytest.skip('Retention fits one response; cross-page coverage is not available')
  count = candle_case.page + STRADDLE_EXTRA
  return result_of(pytestconfig, pytestconfig.stash[SDK], candle_market, count=count)
