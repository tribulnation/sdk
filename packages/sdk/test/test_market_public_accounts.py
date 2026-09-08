"""Public account routing must work without credentials and preserve configured keys."""

from unittest.mock import Mock

import pytest

from tribulnation.sdk import AuthError, MarketSDK
from tribulnation.sdk.impl import accounts


@pytest.mark.parametrize(
  'account',
  [
    accounts.Bybit(
      public=True,
      api_key='$SDK_TEST_MISSING_KEY',
      api_secret='$SDK_TEST_MISSING_SECRET',
    ),
    accounts.Coinbase(
      public=True,
      key_name='$SDK_TEST_MISSING_KEY',
      private_key='$SDK_TEST_MISSING_SECRET',
    ),
    accounts.Binance(
      public=True,
      api_key='$SDK_TEST_MISSING_KEY',
      secret_key='$SDK_TEST_MISSING_SECRET',
    ),
    accounts.Mexc(
      public=True,
      api_key='$SDK_TEST_MISSING_KEY',
      api_secret='$SDK_TEST_MISSING_SECRET',
    ),
    accounts.Dydx(
      public=True, address='$SDK_TEST_MISSING_KEY', mnemonic='$SDK_TEST_MISSING_SECRET'
    ),
  ],
)
async def test_public_market_account_constructs_without_credentials(
  account: accounts.Account,
  monkeypatch: pytest.MonkeyPatch,
):
  """Anonymous venue construction never requires a private key or account address."""
  monkeypatch.delenv('SDK_TEST_MISSING_KEY', raising=False)
  monkeypatch.delenv('SDK_TEST_MISSING_SECRET', raising=False)
  sdk = MarketSDK(accounts={'test': account})
  venue = await sdk.venue('test')
  assert venue.venue_id == account.venue


def test_public_allowed_account_keeps_explicit_credentials(
  monkeypatch: pytest.MonkeyPatch,
):
  """SDK public means missing keys are allowed, not that configured keys are discarded."""
  from tribulnation.bybit import BybitMarket

  factory = Mock()
  monkeypatch.setattr(BybitMarket, 'new', factory)
  MarketSDK().bybit(
    accounts.Bybit(public=True, api_key='test-key', api_secret='test-secret')
  )
  factory.assert_called_once_with(
    'test-key', 'test-secret', public=False, settings={'validate': True}
  )


def test_anonymous_dydx_account_operations_require_an_address():
  """Public indexer use does not fabricate an address for private operations."""
  from tribulnation.dydx.market.impl.mixin import ExchangeMixin

  venue = ExchangeMixin.new()
  with pytest.raises(AuthError, match='address or mnemonic'):
    venue.shared.require_address()
