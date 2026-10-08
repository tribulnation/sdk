"""The tracked `sdk.test.toml` selects one mainnet account for every release venue."""

import tomllib
import pydantic
import pytest
from tribulnation.sdk import MarketSDK
from tribulnation.sdk.impl.accounts import Account
from sdk_dev.cli.results import required_venues, select_account
from sdk_dev.integration.accounts import account_mode
from sdk_dev.repo import repo_root
from sdk_dev.support import load_impl_files, mode_rank

EXPLICIT = {'bitget': 'bitget_classic'}
"""Venues with several mainnet accounts, and the one qualification uses."""


def tracked_sdk() -> MarketSDK:
  """Parse the tracked accounts without reading `.env`: only the layout is checked."""
  with (repo_root() / 'sdk.test.toml').open('rb') as stream:
    data = tomllib.load(stream)
  accounts = pydantic.TypeAdapter(dict[str, Account]).validate_python(data['accounts'])
  return MarketSDK(accounts=accounts)


@pytest.mark.parametrize('venue', required_venues(repo_root(), 'sdk'))
def test_release_venue_selects_its_mainnet_account(venue: str):
  """Qualification needs no ad hoc accounts file and no guessed `--account`."""
  sdk = tracked_sdk()
  selected = select_account(sdk, venue, EXPLICIT.get(venue))
  assert sdk.accounts[selected].venue == venue


def test_bitget_accounts_declare_their_mode():
  """Bitget surfaces refuse an account without an explicit `uta` mode."""
  sdk = tracked_sdk()
  bitget = [a for a in sdk.accounts.values() if a.venue == 'bitget']
  assert bitget and all(isinstance(getattr(a, 'uta', None), bool) for a in bitget)
  assert getattr(sdk.accounts[EXPLICIT['bitget']], 'uta') is False


@pytest.mark.parametrize('venue', required_venues(repo_root(), 'sdk'))
def test_release_account_meets_the_venue_minimum_mode(venue: str):
  """Declared fields alone give the selected account the venue's minimum mode."""
  market = load_impl_files(repo_root() / 'packages/impl')[venue].qualification.market
  if market is None:
    return
  sdk = tracked_sdk()
  account = sdk.accounts[select_account(sdk, venue, EXPLICIT.get(venue))]
  assert mode_rank(account_mode(account, resolve=False)) >= mode_rank(market.min_mode)


def test_aster_and_lighter_qualify_authenticated_accounts():
  """Aster's account reads are signed; Lighter's private reads use a read-only token."""
  accounts = tracked_sdk().accounts
  assert not accounts['aster'].public
  assert account_mode(accounts['aster'], resolve=False) == 'private'
  assert account_mode(accounts['lighter'], resolve=False) == 'token'


def test_testnet_accounts_are_named_as_testnets():
  """A testnet account under a mainnet slug hides that venue's mainnet account."""
  for key, account in tracked_sdk().accounts.items():
    if account.venue.endswith('_testnet'):
      assert key == account.venue
