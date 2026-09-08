"""Pytest fixtures for live report integration tests.

Every account in the configuration whose venue's `impl.toml` declares
`[support.report]` other than `none` is exercised; the venue-to-package mapping mirrors
`ReportSDK.venue`, since the router is the only other place that knows it.
"""

from datetime import datetime, timedelta, timezone
import asyncio
import os

import pytest
from typing_extensions import cast

from tribulnation.sdk import Context, NetworkError, RateLimited, Report, ReportSDK
from sdk_dev.repo import IMPL_DIR, repo_root
from sdk_dev.support import load_impl_files
from ..support import describe_exception
from .support import ReportResult

SDK: pytest.StashKey[ReportSDK] = pytest.StashKey()
HISTORY_WINDOW = timedelta(days=30)
MEXC_SPOT_MARKETS_ENV = 'SDK_DEV_MEXC_SPOT_MARKETS'
"""Comma-separated spot symbols the MEXC fill sweep looks at; MEXC has no account-wide
fills feed, so without it the suite exercises no MEXC spot fills."""

EVM_VENUES = {
  'ethereum',
  'arbitrum',
  'polygon',
  'bnb-chain',
  'base',
  'avalanche',
  'optimism',
  'hyperevm',
}


def package_of(venue: str) -> str:
  """The `packages/impl/<slug>` serving a venue id, as `ReportSDK.venue` routes it."""
  if venue in EVM_VENUES:
    return 'ethereum'
  return venue.removesuffix('_testnet')


def reporting_packages() -> set[str]:
  """Package slugs whose `impl.toml` declares report support other than `none`."""
  impls = load_impl_files(repo_root() / IMPL_DIR)
  return {
    slug
    for slug, impl in impls.items()
    if (entry := impl.support.get('report')) is not None and entry.support != 'none'
  }


def load_sdk(accounts: str) -> ReportSDK:
  """Build the `ReportSDK` under test, with the MEXC fill sweep from the environment."""
  sdk = ReportSDK.load(accounts)
  if markets := os.environ.get(MEXC_SPOT_MARKETS_ENV):
    sdk.config['mexc'] = {'spot_markets': [m.strip() for m in markets.split(',')]}
  return sdk


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Parameterize tests over every configured account with report support."""
  if 'report_account' not in metafunc.fixturenames:
    return

  sdk = metafunc.config.stash.get(SDK, None)
  if sdk is None:
    accounts = cast(str, metafunc.config.getoption('accounts_config'))
    sdk = load_sdk(accounts)
    metafunc.config.stash[SDK] = sdk
  packages = reporting_packages()
  ids = [
    id for id, account in sdk.accounts.items() if package_of(account.venue) in packages
  ]
  metafunc.parametrize('report_account', ids, ids=ids, scope='module')


async def read_report(
  report: Report, *, venue: str, start: datetime, end: datetime
) -> ReportResult:
  """Read one snapshot and one history window, keeping the two failures apart."""
  snapshot = snapshot_failure = records = history_failure = None
  with Context().retried(NetworkError, RateLimited, max_retries=5).use():
    try:
      async with report:
        try:
          snapshot = await report.snapshot()
        except Exception as exception:
          snapshot_failure = describe_exception(exception)
        try:
          records = [record async for record in report.history(start, end)]
        except Exception as exception:
          history_failure = describe_exception(exception)
    except Exception as exception:
      # Entering the report (or leaving it) failed; neither read can be trusted.
      failure = describe_exception(exception)
      snapshot_failure = snapshot_failure or failure
      history_failure = history_failure or failure
  return ReportResult(
    venue=venue,
    start=start,
    end=end,
    snapshot=snapshot,
    snapshot_failure=snapshot_failure,
    records=records,
    history_failure=history_failure,
  )


@pytest.fixture(scope='module')
def report_result(report_account: str, pytestconfig: pytest.Config) -> ReportResult:
  """Read and cache one account's snapshot and last-30-days history for the module."""
  sdk = pytestconfig.stash[SDK]
  venue = sdk.accounts[report_account].venue
  end = datetime.now(timezone.utc)
  start = end - HISTORY_WINDOW
  try:
    report = sdk.venue(report_account)
  except Exception as exception:
    failure = describe_exception(exception)
    return ReportResult(
      venue=venue,
      start=start,
      end=end,
      snapshot_failure=failure,
      history_failure=failure,
    )
  return asyncio.run(read_report(report, venue=venue, start=start, end=end))
