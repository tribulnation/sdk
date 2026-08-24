"""Pytest fixtures for live earn integration tests."""

from collections.abc import Sequence
import asyncio

import pytest
from typing_extensions import cast

from tribulnation.sdk import Context, Earn, EarnSDK, NetworkError, RateLimited
from tribulnation.sdk.earn.instruments import Instrument
from ..support import describe_exception
from .support import EarnResult

IMPLEMENTATIONS: pytest.StashKey[dict[str, Earn]] = pytest.StashKey()


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Parameterize tests over configured earn implementations."""
  if 'earn_account' not in metafunc.fixturenames:
    return

  implementations = metafunc.config.stash.get(IMPLEMENTATIONS, None)
  if implementations is None:
    accounts = cast(str, metafunc.config.getoption('accounts_config'))
    implementations = EarnSDK.load(accounts).all
    metafunc.config.stash[IMPLEMENTATIONS] = implementations
  metafunc.parametrize(
    'earn_account',
    implementations,
    ids=implementations,
    scope='module',
  )


async def fetch_instruments(earn_sdk: Earn) -> Sequence[Instrument]:
  """Fetch earn instruments with retries for transient failures."""
  with Context().retried(NetworkError, RateLimited, max_retries=5).use():
    return await earn_sdk.instruments()


@pytest.fixture(scope='module')
def earn_result(
  earn_account: str,
  pytestconfig: pytest.Config,
) -> EarnResult:
  """Fetch and cache one implementation's result for the test module."""
  earn_sdk = pytestconfig.stash[IMPLEMENTATIONS][earn_account]
  try:
    instruments = asyncio.run(fetch_instruments(earn_sdk))
  except Exception as exception:
    return EarnResult(failure=describe_exception(exception))
  return EarnResult(instruments=instruments)
