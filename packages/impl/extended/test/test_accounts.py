"""`accounts.Extended` resolution and the venues `MarketSDK` and `ReportSDK` build."""

import pytest

from tribulnation.extended import ExtendedMarket, Report
from tribulnation.sdk import MarketSDK, ReportSDK
from tribulnation.sdk.impl import accounts

VARS = ('API_KEY', 'STARK_PRIVATE_KEY', 'STARK_PUBLIC_KEY', 'VAULT')


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch):
  """No credential variable leaks in from the developer's environment."""
  for prefix in ('EXTENDED', 'EXTENDED_TESTNET'):
    for name in VARS:
      monkeypatch.delenv(f'{prefix}_{name}', raising=False)


def test_testnet_variables_never_mix_with_mainnet(monkeypatch: pytest.MonkeyPatch):
  """Each network reads its own prefix; a Stark key needs its vault."""
  monkeypatch.setenv('EXTENDED_API_KEY', 'main-key')
  monkeypatch.setenv('EXTENDED_TESTNET_API_KEY', 'test-key')
  monkeypatch.setenv('EXTENDED_TESTNET_STARK_PRIVATE_KEY', '0x1234')
  testnet = accounts.Extended(venue='extended_testnet')
  assert accounts.Extended().resolved_api_key == 'main-key'
  assert testnet.resolved_api_key == 'test-key'
  with pytest.raises(ValueError, match='EXTENDED_TESTNET_VAULT'):
    testnet.verify_env_vars()
  monkeypatch.setenv('EXTENDED_TESTNET_VAULT', '42')
  testnet.verify_env_vars()
  assert testnet.resolved_vault == '42'


def test_a_private_account_needs_its_api_key():
  """Without an API key only a public account resolves."""
  with pytest.raises(ValueError, match='EXTENDED_API_KEY'):
    accounts.Extended().verify_env_vars()
  accounts.Extended(public=True).verify_env_vars()


async def test_sdks_build_the_keys_sub_account(monkeypatch: pytest.MonkeyPatch):
  """`MarketSDK` signs with the Stark key and vault; `ReportSDK` needs the key alone."""
  monkeypatch.setenv('EXTENDED_TESTNET_API_KEY', 'test-key')
  monkeypatch.setenv('EXTENDED_TESTNET_STARK_PRIVATE_KEY', '0x1234')
  monkeypatch.setenv('EXTENDED_TESTNET_VAULT', '42')
  account = accounts.Extended(venue='extended_testnet')
  venue = MarketSDK({'ext': account}).all['ext']
  assert isinstance(venue, ExtendedMarket)
  credentials = venue.shared.client.credentials
  assert credentials is not None and credentials.api_key == 'test-key'
  assert credentials.stark is not None and credentials.stark.vault == 42
  assert venue.id == 'ext' and venue.venue_id == 'extended_testnet'
  report = ReportSDK({'ext': account}).venue('ext')
  assert isinstance(report, Report) and report.venue_id == 'extended_testnet'
  with pytest.raises(ValueError, match='no API key'):
    ReportSDK({'pub': accounts.Extended(public=True)}).venue('pub')
