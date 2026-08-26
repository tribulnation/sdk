"""Live conformance test: Bitget's UTA-mode auto-detection against `sdk.test.toml`.

Named `suite.py`, not `test_*.py`, so a plain `pytest` run at the repo root does not sweep
it in alongside the offline unit tests; `sdk-dev test bitget` targets it explicitly.
"""

import asyncio
import os

import pytest

from tribulnation.bitget import Bitget as BitgetClient
from tribulnation.sdk.impl.accounts import Bitget, load_accounts

from .conftest import ACCOUNTS_CONFIG_ENV


def bitget_accounts() -> dict[str, Bitget]:
  """Bitget accounts from the accounts config with a declared expected `uta` mode."""
  path = os.environ.get(ACCOUNTS_CONFIG_ENV, 'sdk.test.toml')
  accounts = load_accounts(path)
  return {
    account_id: account
    for account_id, account in accounts.items()
    if isinstance(account, Bitget) and account.uta is not None
  }


async def determine_uta(account: Bitget) -> bool:
  """Auto-detect UTA mode for one account, without an explicit `uta` override."""
  async with BitgetClient.new(
    access_key=account.resolved_access_key,
    secret_key=account.resolved_secret_key,
    passphrase=account.resolved_passphrase,
  ) as client:
    return await client.determine_uta()


ACCOUNTS = bitget_accounts()


@pytest.mark.parametrize('account_id', list(ACCOUNTS), ids=list(ACCOUNTS))
def test_detect_uta(account_id: str):
  """`determine_uta()` should match the account's declared `uta` mode."""
  account = ACCOUNTS[account_id]
  detected = asyncio.run(determine_uta(account))
  assert detected == account.uta, (
    f'Expected uta={account.uta} for "{account_id}", but detected uta={detected}'
  )
