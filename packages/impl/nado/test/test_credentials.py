"""Credential modes: public, address only, and a signing key (owner's or a linked
signer's)."""

import pytest
from eth_account import Account

from tribulnation.nado.core import Shared
from tribulnation.nado.market.markets import NadoPerpMarket
from tribulnation.sdk import AuthError

from .conftest import OWNER, SENDER

KEY = '0x' + '11' * 32
"""A throwaway key: nothing is ever signed or sent with it."""


async def test_public_reads_market_data_only():
  """Without an address nothing names the subaccount: account reads and orders refuse
  before any request."""
  shared = Shared.new()
  assert (shared.owner, shared.sender) == (None, None)
  m = NadoPerpMarket(shared=shared, symbol='BTC-PERP', product_id=2)
  with pytest.raises(AuthError):
    await m.open_orders()
  with pytest.raises(AuthError):
    await m.place_order({'type': 'LIMIT', 'qty': 1, 'price': 1})


def test_an_address_names_the_default_subaccount():
  """An address alone reads its `default` subaccount, or the one named; it signs
  nothing."""
  shared = Shared.new(address=OWNER)
  assert shared.sender is not None and shared.sender.lower() == SENDER
  assert shared.client.credentials is None
  named = Shared.new(address=OWNER, subaccount='bot')
  assert named.sender is not None and named.sender != shared.sender


def test_a_key_reads_and_signs_for_its_own_address_or_the_owner_given():
  """A key alone is its own wallet's; with `address`, a linked signer's for that
  owner, and reads go to the owner's subaccount."""
  own = Shared.new(private_key=KEY)
  assert own.owner is not None
  assert own.owner.lower() == Account.from_key(KEY).address.lower()
  linked = Shared.new(private_key=KEY, address=OWNER)
  assert linked.owner is not None and linked.owner.lower() == OWNER
  assert linked.sender is not None and linked.sender.lower() == SENDER
  assert linked.require_signer().lower() == SENDER


def test_the_testnet_is_its_own_venue():
  """`testnet` reports `nado_testnet`."""
  assert Shared.new(network='testnet').venue_id == 'nado_testnet'
