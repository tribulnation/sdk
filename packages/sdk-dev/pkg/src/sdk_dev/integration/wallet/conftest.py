"""Pytest fixtures for live wallet integration tests."""

from collections.abc import Sequence
import asyncio

import pytest
from typing_extensions import cast

from tribulnation.sdk import Context, NetworkError, RateLimited, Wallet, WalletSDK
from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod
from ..support import describe_exception
from .support import WalletResult

IMPLEMENTATIONS: pytest.StashKey[dict[str, Wallet]] = pytest.StashKey()


def pytest_generate_tests(metafunc: pytest.Metafunc):
  """Parameterize tests over configured wallet implementations."""
  if 'wallet_account' not in metafunc.fixturenames:
    return

  implementations = metafunc.config.stash.get(IMPLEMENTATIONS, None)
  if implementations is None:
    accounts = cast(str, metafunc.config.getoption('accounts_config'))
    wallet = WalletSDK.load(accounts)
    implementations = {
      account_id: wallet.venue(account_id)
      for account_id, account in wallet.all_accounts.items()
      if account.venue in {'binance', 'bitget', 'mexc'}
    }
    metafunc.config.stash[IMPLEMENTATIONS] = implementations
  metafunc.parametrize(
    'wallet_account',
    implementations,
    ids=implementations,
    scope='module',
  )


async def fetch_wallet(wallet_sdk: Wallet) -> WalletResult:
  """Fetch wallet methods, preserving independent endpoint failures."""
  deposit_methods: Sequence[DepositMethod] | None = None
  deposit_failure: str | None = None
  withdrawal_methods: Sequence[WithdrawalMethod] | None = None
  withdrawal_failure: str | None = None

  with Context().retried(NetworkError, RateLimited, max_retries=5).use():
    try:
      deposit_methods = await wallet_sdk.deposit_methods()
    except Exception as exception:
      deposit_failure = describe_exception(exception)
    try:
      withdrawal_methods = await wallet_sdk.withdrawal_methods()
    except Exception as exception:
      withdrawal_failure = describe_exception(exception)

  return WalletResult(
    deposit_methods=deposit_methods,
    deposit_failure=deposit_failure,
    withdrawal_methods=withdrawal_methods,
    withdrawal_failure=withdrawal_failure,
  )


@pytest.fixture(scope='module')
def wallet_result(
  wallet_account: str,
  pytestconfig: pytest.Config,
) -> WalletResult:
  """Fetch and cache one wallet implementation's result for the test module."""
  wallet_sdk = pytestconfig.stash[IMPLEMENTATIONS][wallet_account]
  return asyncio.run(fetch_wallet(wallet_sdk))
