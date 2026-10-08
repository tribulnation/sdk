"""Credential modes: API key, read-only auth token, and public account reads."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing_extensions import Any, cast

import pytest
from typed_lighter import Lighter as Client

from tribulnation.lighter import LighterMarket
from tribulnation.lighter.core import Shared, master_index
from tribulnation.lighter.market import orders
from tribulnation.lighter.market.markets import LighterPerpMarket
from tribulnation.sdk import MarketSDK
from tribulnation.sdk.core import AuthError
from tribulnation.sdk.impl.accounts import Lighter

TOKEN = 'ro:476:single:1999999999:abcdef'
"""A read-only token's shape; never sent anywhere."""
VARIABLES = [
  f'{prefix}_{name}'
  for prefix in ('LIGHTER', 'LIGHTER_TESTNET')
  for name in (
    'ACCOUNT_INDEX',
    'API_KEY_INDEX',
    'API_PRIVATE_KEY',
    'AUTH_TOKEN',
    'ADDRESS',
    'ETH_PRIVATE_KEY',
  )
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch):
  """No ambient Lighter credentials."""
  for name in VARIABLES:
    monkeypatch.delenv(name, raising=False)


def test_a_token_replaces_the_api_key_in_verification(monkeypatch: pytest.MonkeyPatch):
  """A private account needs an API key or a token, from its own network only."""
  with pytest.raises(ValueError):
    Lighter().verify_env_vars()
  monkeypatch.setenv('LIGHTER_TESTNET_AUTH_TOKEN', TOKEN)
  with pytest.raises(ValueError):
    Lighter().verify_env_vars()
  Lighter(venue='lighter_testnet').verify_env_vars()
  monkeypatch.setenv('LIGHTER_AUTH_TOKEN', TOKEN)
  account = Lighter()
  account.verify_env_vars()
  assert account.resolved_auth_token == TOKEN
  assert account.resolved_api_private_key is None
  assert Lighter(auth_token='$OTHER', public=True).resolved_auth_token is None


def venue(account: Lighter) -> LighterMarket:
  """The market venue `MarketSDK` builds for an account."""
  built = MarketSDK({'acct': account}).all['acct']
  assert isinstance(built, LighterMarket)
  return built


def test_a_token_builds_a_read_only_client():
  """Token reads use the token's account; trading names the missing API key."""
  shared = venue(Lighter(auth_token=TOKEN)).shared
  assert shared.private_index == 476
  with pytest.raises(AuthError, match='needs an API key'):
    shared.require_api_key()


def test_a_public_account_keeps_its_index_and_address():
  """Public accounts keep `account_index` and `address` for public account reads."""
  shared = venue(Lighter(account_index=7, address='0xabc', public=True)).shared
  assert shared.client.account_index is None
  assert (shared.public_index, shared.address) == (7, '0xabc')
  with pytest.raises(AuthError, match='API key or a read-only auth token'):
    shared.private_index


def stub(*, credentials: int | None = None, **fields: Any) -> tuple[Shared, AsyncMock]:
  """A shared owner over a stub client whose address lookup returns a sub-account
  listed before its master."""
  get = AsyncMock(
    return_value={
      'accounts': [{'index': 9, 'account_type': 1}, {'index': 8, 'account_type': 0}]
    }
  )
  client = SimpleNamespace(
    account_index=credentials,
    account_signer=None,
    api=SimpleNamespace(account=SimpleNamespace(get=get)),
  )
  return Shared(client=cast(Client, client), **fields), get


async def test_the_address_resolves_to_its_master_account_once():
  """Without an index, public reads use the address's master account, looked up once."""
  shared, get = stub(address='0xabc')
  assert await shared.account_index() == 8
  assert await shared.account_index() == 8
  get.assert_awaited_once_with({'by': 'l1_address', 'value': '0xabc'})


async def test_credentials_and_explicit_indexes_win_over_the_address():
  """The credentials' account, then `account_index`, then the address."""
  shared, get = stub(credentials=5, public_index=6, address='0xabc')
  assert await shared.account_index() == 5
  shared, get = stub(public_index=6, address='0xabc')
  assert await shared.account_index() == 6
  get.assert_not_awaited()


async def test_no_account_is_an_auth_error():
  """Account reads without any account name what to configure."""
  shared, _ = stub()
  with pytest.raises(AuthError, match='`account_index` or an `address`'):
    await shared.account_index()


def test_an_address_without_master_account_is_rejected():
  """Only `account_type` 0 is a master account."""
  with pytest.raises(ValueError, match='no master account'):
    master_index([cast(Any, {'index': 9, 'account_type': 1})], '0xabc')


async def test_token_gated_reads_and_trading_fail_before_any_request():
  """Fees, open orders and orders need a token; trading needs an API key."""
  shared, get = stub(address='0xabc')
  market = LighterPerpMarket(shared=shared, market_index=0)
  with pytest.raises(AuthError, match='auth token'):
    await market.fees()
  with pytest.raises(AuthError, match='auth token'):
    await market.open_orders()
  with pytest.raises(AuthError, match='auth token'):
    await market.query_order('1')
  with pytest.raises(AuthError, match='needs an API key'):
    await orders.place_order(shared, 0, {'qty': '0.01', 'price': '1', 'type': 'LIMIT'})
  with pytest.raises(AuthError, match='needs an API key'):
    await market.cancel_open_orders()
  get.assert_not_awaited()
