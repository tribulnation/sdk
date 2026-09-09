"""Select integration accounts without constructing unrelated clients."""

from collections.abc import Mapping
from pathlib import Path
import tomllib

import pydantic
import pytest
from typing_extensions import cast

from tribulnation.sdk.impl.accounts import Account
from sdk_dev.repo import IMPL_DIR, repo_root
from sdk_dev.support import ImplSurfaceSupport, load_impl_files

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
  """Map router venue names to their implementation package."""
  return 'ethereum' if venue in EVM_VENUES else venue.removesuffix('_testnet')


def load_accounts(config: pytest.Config) -> dict[str, Account]:
  """Parse configuration; check credentials only when a selected account runs."""
  path = Path(cast(str, config.getoption('accounts_config'))).expanduser()
  with path.open('rb') as source:
    data = tomllib.load(source)
  return pydantic.TypeAdapter(dict[str, Account]).validate_python(
    data.get('accounts', {})
  )


def surface_support(surface: str) -> dict[str, ImplSurfaceSupport]:
  """Read the declared support instead of maintaining another venue allowlist."""
  return {
    slug: entry
    for slug, impl in load_impl_files(repo_root() / IMPL_DIR).items()
    if (entry := impl.support.get(surface)) is not None and entry.support != 'none'
  }


def selected_accounts(
  config: pytest.Config,
  accounts: Mapping[str, Account],
  *,
  surface: str,
) -> list[str]:
  """Select an exact account id or venue slug before any client is constructed."""
  selector = cast(str | None, config.getoption('sdk_venue'))
  supported = surface_support(surface)
  if (
    selector is not None
    and selector not in supported
    and not any(selector in (id, account.venue) for id, account in accounts.items())
  ):
    raise pytest.UsageError('Unknown venue or account selector')
  return [
    id
    for id, account in accounts.items()
    if package_of(account.venue) in supported
    and (selector is None or selector in (id, account.venue))
  ]


def require_credentials(account: Account, *, auth: bool = False):
  """Report missing configured environment variables as a setup skip, not a pass."""
  if auth and account.public:
    pytest.skip('This surface requires a configured private account')
  try:
    account.verify_env_vars()
  except ValueError:
    pytest.skip('Missing required credential environment variable for this account')
