"""Entering a signed venue settles the account its key acts for (`getUser`), offline."""

from unittest.mock import AsyncMock

import pytest
from typed_margin_trade import MarginTrade, Wallet
from typed_margin_trade.user.get_user import GetUser

from tribulnation.margin_trade.core import Shared
from tribulnation.sdk.core import AuthError

MASTER = '5sXTVgMasterAccount1111111111111111111111'


def shared(address: str | None) -> Shared:
  """A testnet owner signed by a fresh key, configured with `address`."""
  client = MarginTrade.new(Wallet.generate(), mainnet=False)
  return Shared(client=client, mainnet=False, maybe_address=address)


@pytest.fixture
def get_user(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
  """`getUser` naming `MASTER` as the key's master account."""
  endpoint = AsyncMock(return_value={'masterAccount': MASTER})
  monkeypatch.setattr(GetUser, 'get_user', endpoint)
  return endpoint


async def test_another_address_than_the_master_raises(get_user: AsyncMock):
  """A key acting for another account than `address` would read one and trade another."""
  owner = shared('SomeOtherAccount')
  with pytest.raises(AuthError, match=MASTER):
    async with owner:
      pass


async def test_omitted_address_is_the_master(get_user: AsyncMock):
  """Without `address`, reads go to the master account, not the key's own address."""
  owner = shared(None)
  async with owner:
    assert owner.address == MASTER
  assert owner.address != owner.client.account


async def test_the_master_address_enters(get_user: AsyncMock):
  """The configured master passes the check."""
  owner = shared(MASTER)
  async with owner:
    assert owner.address == MASTER
  get_user.assert_awaited_once()


async def test_a_public_client_skips_the_check(get_user: AsyncMock):
  """Address-only reads need no key and send no signed request."""
  owner = Shared(
    client=MarginTrade.new(public=True, mainnet=False),
    mainnet=False,
    maybe_address=MASTER,
  )
  async with owner:
    assert owner.address == MASTER
  get_user.assert_not_awaited()
