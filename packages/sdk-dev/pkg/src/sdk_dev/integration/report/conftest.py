"""Pytest fixtures for live report integration tests.

Every account in the configuration whose venue's `impl.toml` declares
`[support.report]` other than `none` is exercised; the venue-to-package mapping mirrors
`ReportSDK.venue`, since the router is the only other place that knows it.

Every account is built and read on one event loop kept for the whole session, the way
a consumer iterating `report.all` would: some clients bind a lock or a semaphore to
the loop they first run on, and one `asyncio.run` per account trips over that.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tomllib

import pydantic
import pytest

from tribulnation.sdk import Context, NetworkError, RateLimited, Report, ReportSDK
from ..accounts import load_accounts, selected_accounts, require_report_credentials
from ..support import describe_exception
from ..runtime import loop_of
from .support import ReportResult

SDK: pytest.StashKey[ReportSDK] = pytest.StashKey()
HISTORY_WINDOW = timedelta(days=30)


def load_sdk(config: pytest.Config) -> ReportSDK:
  """Build the report router; implementations discover their own history markets."""
  sdk = ReportSDK(accounts=load_accounts(config))
  account_path = config.getoption('accounts_config')
  if not isinstance(account_path, str):
    raise ValueError('Report tests require an accounts configuration path')
  path = Path(account_path).expanduser()
  with path.open('rb') as source:
    settings = tomllib.load(source).get('report', {})
  if settings:
    if set(settings) != {'dydx'}:
      raise ValueError('Supported Report test configuration: report.dydx')
    from tribulnation.dydx.report import DydxConfig

    sdk.config['dydx'] = pydantic.TypeAdapter(DydxConfig).validate_python(
      settings['dydx']
    )
  return sdk


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Parameterize tests over every configured account with report support."""
  if 'report_account' not in metafunc.fixturenames:
    return

  sdk = metafunc.config.stash.get(SDK, None)
  if sdk is None:
    sdk = load_sdk(metafunc.config)
    metafunc.config.stash[SDK] = sdk
  ids = selected_accounts(metafunc.config, sdk.accounts, surface='report')
  metafunc.parametrize('report_account', ids, ids=ids, scope='module')


async def read_report(
  sdk: ReportSDK, id: str, *, venue: str, start: datetime, end: datetime
) -> ReportResult:
  """Build one account's report and read a snapshot and a history window, keeping
  the two failures apart."""
  snapshot = snapshot_failure = records = history_failure = None
  with Context().retried(NetworkError, RateLimited, max_retries=5).use():
    try:
      report: Report = sdk.venue(id)
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
      # Building, entering or leaving the report failed; neither read can be trusted.
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
  require_report_credentials(sdk.accounts[report_account])
  venue = sdk.accounts[report_account].venue
  end = datetime.now(timezone.utc)
  start = end - HISTORY_WINDOW
  return loop_of(pytestconfig).run_until_complete(
    read_report(sdk, report_account, venue=venue, start=start, end=end)
  )
