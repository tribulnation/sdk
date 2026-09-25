"""The tracked `sdk.test.toml` selects one mainnet account for every release venue."""

import tomllib
import pydantic
import pytest
from tribulnation.sdk import MarketSDK
from tribulnation.sdk.impl.accounts import Account
from sdk_dev.cli.results import required_venues, select_account
from sdk_dev.repo import repo_root

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
  assert sdk.all_accounts[selected].venue == venue
  if venue not in EXPLICIT:
    assert selected in sdk.accounts, 'a public default would hide a misconfiguration'


def test_bitget_accounts_declare_their_mode():
  """Bitget surfaces refuse an account without an explicit `uta` mode."""
  sdk = tracked_sdk()
  bitget = [a for a in sdk.accounts.values() if a.venue == 'bitget']
  assert bitget and all(isinstance(getattr(a, 'uta', None), bool) for a in bitget)
  assert getattr(sdk.accounts[EXPLICIT['bitget']], 'uta') is False


def test_testnet_accounts_are_named_as_testnets():
  """A testnet account under a mainnet slug hides that venue's mainnet account."""
  for key, account in tracked_sdk().accounts.items():
    if account.venue.endswith('_testnet'):
      assert key == account.venue
