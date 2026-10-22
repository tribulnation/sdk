"""Credential modes: explicit construction, never the environment, and SDK routing."""

import pytest
from typing_extensions import cast

from tribulnation.grvt import GrvtMarket
from tribulnation.grvt.core import ORDER_TTL, Shared
from tribulnation.sdk import MarketSDK, ReportSDK
from tribulnation.sdk.impl import accounts

KEY = '0x' + '11' * 32
"""A well-formed signer key, never used to sign here."""


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch):
  """Credentials the adapter must never pick up on its own."""
  for prefix in ('GRVT_', 'GRVT_TESTNET_'):
    monkeypatch.setenv(f'{prefix}API_KEY', 'from-the-environment')
    monkeypatch.setenv(f'{prefix}PRIVATE_KEY', KEY)
    monkeypatch.setenv(f'{prefix}TRADING_ACCOUNT_ID', '999')


def test_without_an_api_key_the_client_is_public():
  """No API key: market data only, whatever the environment holds."""
  shared = Shared.new()
  assert shared.client.session is None
  assert shared.client.trading_client.signer is None
  assert shared.venue_id == 'grvt'


def test_explicit_credentials_are_the_only_ones_used():
  """The API key, signer key and sub-account given; orders sign for `ORDER_TTL`."""
  shared = Shared.new(
    env='testnet', api_key='explicit', private_key=KEY, trading_account_id='5'
  )
  session = shared.client.session
  assert session is not None and session.api_key == 'explicit'
  trading = shared.client.trading_client
  assert trading.signer is not None and trading.signature_ttl == ORDER_TTL
  assert trading.trading_account_id == '5'
  assert shared.venue_id == 'grvt_testnet'


def test_a_read_only_key_cannot_sign():
  """An API key alone opens a session without a signer."""
  shared = Shared.new(api_key='explicit')
  assert shared.client.session is not None
  assert shared.client.trading_client.signer is None


def test_a_private_key_needs_its_api_key():
  """A signer key alone is refused rather than logging in as a funding wallet."""
  with pytest.raises(ValueError):
    Shared.new(private_key=KEY)


def test_market_sdk_builds_from_the_account():
  """`MarketSDK` resolves the account and passes every credential explicitly."""
  account = accounts.Grvt(
    venue='grvt_testnet', api_key='k', private_key=KEY, trading_account_id='5'
  )
  venue = cast(GrvtMarket, MarketSDK({'g': account}).all['g'])
  assert (venue.id, venue.venue_id) == ('g', 'grvt_testnet')
  client = venue.shared.client
  assert client.session is not None and client.session.api_key == 'k'
  assert client.trading_client.trading_account_id == '5'


def test_accounts_default_to_their_network_variables(monkeypatch: pytest.MonkeyPatch):
  """Omitted fields read the network's own variables; testnet never reads mainnet's."""
  monkeypatch.setenv('GRVT_TESTNET_API_KEY', 'testnet-key')
  account = accounts.Grvt(venue='grvt_testnet')
  assert account.resolved_api_key == 'testnet-key'
  assert account.resolved_trading_account_id == '999'
  monkeypatch.delenv('GRVT_TESTNET_API_KEY')
  with pytest.raises(ValueError):
    account.verify_env_vars()
  public = accounts.Grvt(venue='grvt_testnet', public=True)
  public.verify_env_vars()
  venue = cast(GrvtMarket, MarketSDK({'p': public}).all['p'])
  assert venue.shared.client.session is None


def test_report_sdk_needs_an_api_key(monkeypatch: pytest.MonkeyPatch):
  """Snapshots read the account, so a keyless account is refused up front."""
  monkeypatch.delenv('GRVT_API_KEY')
  with pytest.raises(ValueError):
    ReportSDK({'g': accounts.Grvt(public=True)}).venue('g')
  report = ReportSDK({'g': accounts.Grvt(api_key='k')}).venue('g')
  assert report is not None
