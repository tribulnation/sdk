"""Pytest fixtures for live report integration tests.

Every account in the configuration whose venue's `impl.toml` declares
`[support.report]` other than `none` is exercised; the venue-to-package mapping mirrors
`ReportSDK.venue`, since the router is the only other place that knows it.

Every account is built and read on one event loop kept for the whole session, the way
a consumer iterating `report.all` would: some clients bind a lock or a semaphore to
the loop they first run on, and one `asyncio.run` per account trips over that.
"""

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


def load_sdk(config: pytest.Config) -> ReportSDK:
  """Build the report router with its configured snapshot providers."""
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


async def read_report(sdk: ReportSDK, id: str) -> ReportResult:
  """Read one snapshot and retain sanitized request or lifecycle failures."""
  snapshot = None
  snapshot_failure = None
  with Context().retried(NetworkError, RateLimited, max_retries=5).use():
    try:
      report: Report = sdk.venue(id)
      async with report:
        snapshot = await report.snapshot()
    except Exception as exception:
      snapshot_failure = describe_exception(exception)
  return ReportResult(snapshot=snapshot, snapshot_failure=snapshot_failure)


@pytest.fixture(scope='module')
def report_result(report_account: str, pytestconfig: pytest.Config) -> ReportResult:
  """Read and cache one account's snapshot for the module."""
  sdk = pytestconfig.stash[SDK]
  require_report_credentials(sdk.accounts[report_account])
  return loop_of(pytestconfig).run_until_complete(read_report(sdk, report_account))
