"""New venue routing and mainnet/testnet credential separation."""

import pytest
from tribulnation.sdk import EarnSDK, ReportSDK, WalletSDK
from tribulnation.sdk.impl.accounts import Account, Deribit, Kucoin


@pytest.mark.parametrize('root', [EarnSDK, ReportSDK, WalletSDK])
@pytest.mark.parametrize(
  'account',
  [
    Kucoin(public=True),
    Deribit(public=True),
    Deribit(venue='deribit_testnet', public=True),
  ],
)
def test_venues_construct_through_each_router(
  root: type[EarnSDK] | type[ReportSDK] | type[WalletSDK], account: Account
):
  """Every implemented surface is reachable without direct package imports."""
  sdk = root(accounts={'venue': account})
  assert sdk.venue('venue') is not None


def test_deribit_test_credentials_do_not_fall_back_on_mainnet(
  monkeypatch: pytest.MonkeyPatch,
):
  """Only the explicitly selected testnet account resolves TEST_ credentials."""
  monkeypatch.delenv('DERIBIT_CLIENT_ID', raising=False)
  monkeypatch.delenv('DERIBIT_CLIENT_SECRET', raising=False)
  monkeypatch.setenv('TEST_DERIBIT_CLIENT_ID', 'test-only-id')
  monkeypatch.setenv('TEST_DERIBIT_CLIENT_SECRET', 'test-only-secret')
  with pytest.raises(ValueError, match='DERIBIT_CLIENT_ID'):
    Deribit().verify_env_vars()
  account = Deribit(venue='deribit_testnet')
  account.verify_env_vars()
  assert account.resolved_client_id == 'test-only-id'
