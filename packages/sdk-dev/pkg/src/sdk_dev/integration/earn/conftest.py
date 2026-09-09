"""Pytest fixtures for live earn integration tests."""

from collections.abc import Sequence

import pytest

from tribulnation.sdk import Context, Earn, EarnSDK, NetworkError, RateLimited
from tribulnation.sdk.earn.instruments import Instrument
from ..support import describe_exception
from ..runtime import loop_of
from ..accounts import (
  load_accounts,
  selected_accounts,
  require_credentials,
  surface_support,
  package_of,
)
from .support import EarnResult

SDK: pytest.StashKey[EarnSDK] = pytest.StashKey()


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Parameterize tests over configured earn implementations."""
  if 'earn_account' not in metafunc.fixturenames:
    return

  sdk = metafunc.config.stash.get(SDK, None)
  if sdk is None:
    sdk = EarnSDK(accounts=load_accounts(metafunc.config))
    metafunc.config.stash[SDK] = sdk
  ids = selected_accounts(metafunc.config, sdk.all_accounts, surface='earn')
  metafunc.parametrize(
    'earn_account',
    ids,
    ids=ids,
    scope='module',
  )


async def fetch_instruments(earn_sdk: Earn) -> Sequence[Instrument]:
  """Fetch earn instruments with retries for transient failures."""
  with Context().retried(NetworkError, RateLimited, max_retries=5).use():
    async with earn_sdk:
      return await earn_sdk.instruments()


async def read_account(sdk: EarnSDK, id: str) -> Sequence[Instrument]:
  """Construct the client on the same loop used to read and close it."""
  return await fetch_instruments(sdk.venue(id))


@pytest.fixture(scope='module')
def earn_result(
  earn_account: str,
  pytestconfig: pytest.Config,
) -> EarnResult:
  """Fetch and cache one implementation's result for the test module."""
  sdk = pytestconfig.stash[SDK]
  account = sdk.all_accounts[earn_account]
  support = surface_support('earn')[package_of(account.venue)]
  require_credentials(account, auth=support.auth)
  try:
    instruments = loop_of(pytestconfig).run_until_complete(
      read_account(sdk, earn_account)
    )
  except Exception as exception:
    return EarnResult(failure=describe_exception(exception))
  return EarnResult(instruments=instruments)
