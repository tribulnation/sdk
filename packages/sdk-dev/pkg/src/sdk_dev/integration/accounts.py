"""Select integration accounts without constructing unrelated clients."""

from collections.abc import Mapping
import dataclasses
from pathlib import Path
import tomllib

import pydantic
import pytest
from typing_extensions import cast

from tribulnation.sdk.impl.accounts import Account, Aster, Dydx, Hyperliquid, Lighter
from sdk_dev.repo import IMPL_DIR, repo_root
from sdk_dev.support import AccountMode, ImplSurfaceSupport, load_impl_files

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


def configured(account: Account, name: str, *, resolve: bool) -> bool:
  """Whether a credential field is set: resolved through the environment (property
  defaults included), or else declared. Undeclared, a secret counts only when it differs
  from its field default, while an identifier's `$VAR` default already names one."""
  if resolve:
    try:
      value = getattr(account, f'resolved_{name}')
    except ValueError:
      return False
    return value is not None and value != ''
  value = getattr(account, name)
  if name in ('address', 'account_index', 'user'):
    # Identifiers, not secrets: a `$VAR` default names the intended account.
    return value is not None and value != ''
  default = next(f.default for f in dataclasses.fields(account) if f.name == name)
  return value is not None and value != default


def account_mode(account: Account, *, resolve: bool = True) -> AccountMode:
  """The authority an account configuration gives the Market client built from it.

  With `resolve`, credentials count only when their environment variables are set,
  which is what a live run actually has; without it, only the declared fields count,
  so the tracked configuration can be checked without reading `.env`.
  """
  if isinstance(account, Lighter):
    if not account.public and not resolve:
      return (
        'token' if account.auth_token and not account.api_private_key else 'private'
      )
    if configured(account, 'api_private_key', resolve=resolve):
      return 'private'
    if configured(account, 'auth_token', resolve=resolve):
      return 'token'
    if configured(account, 'address', resolve=resolve) or configured(
      account, 'account_index', resolve=resolve
    ):
      return 'address'
    return 'public'
  if isinstance(account, Aster):
    if not account.public and not resolve:
      return 'private'
    signed = configured(account, 'user', resolve=resolve) and configured(
      account, 'signer', resolve=resolve
    )
    return 'private' if signed else 'public'
  if not account.public:
    if not resolve:
      return 'private'
    try:
      account.verify_env_vars()
    except ValueError:
      return 'public'
    return 'private'
  if isinstance(account, Hyperliquid) and configured(
    account, 'private_key', resolve=resolve
  ):
    return 'private'
  if isinstance(account, (Dydx, Hyperliquid)) and configured(
    account, 'address', resolve=resolve
  ):
    return 'address'
  return 'public'


def require_report_credentials(account: Account):
  """Public chain/indexer reports need an address, never a signing secret; Aster's
  are signed by the trading agent, even on an account whose market data is public."""
  if isinstance(account, Aster):
    try:
      configured = account.resolved_user and account.resolved_signer
    except ValueError:
      configured = None
    if not configured:
      pytest.skip('Report checks require a configured user and signer')
    return
  if isinstance(account, Lighter):
    try:
      owner = account.resolved_address or account.resolved_account_index
    except ValueError:
      owner = None
    if owner is None:
      pytest.skip('Report checks require a configured address or account index')
    return
  if isinstance(account, (Dydx, Hyperliquid)):
    try:
      address = account.resolved_address
    except ValueError:
      address = None
    if not address:
      pytest.skip('Report checks require a configured address')
    return
  require_credentials(account, auth=True)
