"""Pytest fixtures for live wallet integration tests."""

import pytest

from tribulnation.sdk import Context, NetworkError, RateLimited, Wallet, WalletSDK
from ..support import describe_exception
from ..runtime import loop_of
from ..accounts import (
  load_accounts,
  selected_accounts,
  require_credentials,
  surface_support,
  package_of,
)
from .support import WalletResult

SDK: pytest.StashKey[WalletSDK] = pytest.StashKey()


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Parameterize tests over configured wallet implementations."""
  if 'wallet_account' not in metafunc.fixturenames:
    return

  sdk = metafunc.config.stash.get(SDK, None)
  if sdk is None:
    sdk = WalletSDK(accounts=load_accounts(metafunc.config))
    metafunc.config.stash[SDK] = sdk
  ids = selected_accounts(metafunc.config, sdk.all_accounts, surface='wallet')
  metafunc.parametrize(
    'wallet_account',
    ids,
    ids=ids,
    scope='module',
  )


async def fetch_wallet(
  wallet_sdk: Wallet, *, methods: list[str] | None = None
) -> WalletResult:
  """Fetch wallet methods, preserving independent endpoint failures."""
  with Context().retried(NetworkError, RateLimited, max_retries=5).use():
    async with wallet_sdk:
      return await read_wallet(wallet_sdk, methods=methods)


async def read_wallet(
  wallet_sdk: Wallet, *, methods: list[str] | None = None
) -> WalletResult:
  """Read declared methods; an unexpected NotImplementedError is a real failure."""
  deposit_methods = withdrawal_methods = None
  deposit_failure = withdrawal_failure = None
  deposit_unsupported = withdrawal_unsupported = None
  if methods is None or 'deposit_methods' in methods:
    try:
      deposit_methods = await wallet_sdk.deposit_methods()
    except Exception as exception:
      deposit_failure = describe_exception(exception)
  else:
    deposit_unsupported = 'deposit_methods is not declared in impl.toml'
  if methods is None or 'withdrawal_methods' in methods:
    try:
      withdrawal_methods = await wallet_sdk.withdrawal_methods()
    except Exception as exception:
      withdrawal_failure = describe_exception(exception)
  else:
    withdrawal_unsupported = 'withdrawal_methods is not declared in impl.toml'

  return WalletResult(
    deposit_methods=deposit_methods,
    deposit_failure=deposit_failure,
    deposit_unsupported=deposit_unsupported,
    withdrawal_methods=withdrawal_methods,
    withdrawal_failure=withdrawal_failure,
    withdrawal_unsupported=withdrawal_unsupported,
  )


@pytest.fixture(scope='module')
def wallet_result(
  wallet_account: str,
  pytestconfig: pytest.Config,
) -> WalletResult:
  """Fetch and cache one wallet implementation's result for the test module."""
  sdk = pytestconfig.stash[SDK]
  account = sdk.all_accounts[wallet_account]
  support = surface_support('wallet')[package_of(account.venue)]
  require_credentials(account, auth=support.auth)
  methods = support.methods if support.support == 'partial' else None
  try:
    return loop_of(pytestconfig).run_until_complete(
      read_account(sdk, wallet_account, methods=methods)
    )
  except Exception as exception:
    failure = describe_exception(exception)
    return WalletResult(deposit_failure=failure, withdrawal_failure=failure)


async def read_account(
  sdk: WalletSDK, id: str, *, methods: list[str] | None
) -> WalletResult:
  """Construct, read and close one client on the integration-session loop."""
  return await fetch_wallet(sdk.venue(id), methods=methods)
