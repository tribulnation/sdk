"""Account routing, credential isolation and explicitly unsupported methods."""

from datetime import datetime, timezone
from pathlib import Path
from typing_extensions import Literal
from eth_account import Account
import pytest
from tribulnation.aster import AsterMarket, Report
from tribulnation.aster.market.markets import PerpMarket, SpotMarket
from tribulnation.sdk import AuthError, MarketSDK
from tribulnation.sdk.impl.accounts import Aster, load_accounts


@pytest.mark.parametrize('venue_id', ['aster', 'aster_testnet'])
@pytest.mark.parametrize('validate', [None, True, False])
async def test_account_validation_reaches_every_transport(
  venue_id: Literal['aster', 'aster_testnet'], validate: bool | None
):
  """Public construction accepts the router's validate argument and propagates it."""
  account = Aster(venue=venue_id, public=True)
  if validate is not None:
    account = Aster(venue=venue_id, public=True, validate=validate)
  async with MarketSDK({venue_id: account}) as sdk:
    venue = await sdk.venue(venue_id)
    assert isinstance(venue, AsterMarket)
    client = venue.client
    expected = True if validate is None else validate
    for surface in (client.futures, client.spot, client.prediction):
      assert surface.client.validate is expected
      assert surface.streams_client.validate is expected
      assert surface.user_stream_client.validate is expected
    assert client.chain.client.validate is expected
    assert client.chain.rpc_client.validate is expected
    assert client.bapi_client.validate is expected


def test_testnet_credentials_do_not_fall_back_to_mainnet(
  monkeypatch: pytest.MonkeyPatch,
):
  """Mainnet keys, including the main-wallet key, never reach a testnet client."""
  monkeypatch.setenv('ASTER_USER', Account.create().address)
  monkeypatch.setenv('ASTER_SIGNER_PRIVATE_KEY', Account.create().key.hex())
  monkeypatch.setenv('ASTER_USER_PRIVATE_KEY', Account.create().key.hex())
  monkeypatch.delenv('TEST_ASTER_USER', raising=False)
  monkeypatch.delenv('TEST_ASTER_SIGNER_PRIVATE_KEY', raising=False)
  with pytest.raises(ValueError, match='TEST_ASTER_USER'):
    Aster(venue='aster_testnet').verify_env_vars()
  with pytest.raises(AuthError, match='signer'):
    AsterMarket.new(mainnet=False)
  user, agent = Account.create(), Account.create()
  venue = AsterMarket.new(user=user.address, signer=agent.key.hex(), mainnet=False)
  credentials = venue.client.futures.client.credentials
  assert credentials is not None and credentials.user == user.address
  assert credentials.agent is not None and credentials.agent.address == agent.address
  assert credentials.main is None
  assert venue.client.spot.client.credentials is credentials
  assert venue.client.prediction.client.credentials is None
  assert venue.client.chain.client.credentials is None


async def test_toml_routes_both_networks(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
  """TOML accounts select the network, share one owner and resolve exchanges."""
  monkeypatch.setattr('os.environ', {})
  path = tmp_path / 'sdk.toml'
  path.write_text(
    '[accounts.main]\nvenue="aster"\npublic=true\n'
    '[accounts.test]\nvenue="aster_testnet"\npublic=true\nvalidate=false\n'
  )
  sdk = MarketSDK(accounts=load_accounts(path))
  async with sdk:
    venue = await sdk.venue('test')
    assert venue is await sdk.venue('test')
    assert venue.venue_id == 'aster_testnet'
    assert [r['id'] for r in await venue.exchanges()] == ['spot', 'perp']
    assert await venue.perp_exchange('perp') is await venue.exchange('perp')
    with pytest.raises(ValueError, match='perpetual exchange'):
      await venue.perp_exchange('spot')
    with pytest.raises(ValueError, match='Unknown Aster exchange'):
      await venue.exchange('inverse')
    assert (await sdk.venue('main')).venue_id == 'aster'
  user, agent = Account.create(), Account.create()
  private = Aster(
    venue='aster_testnet', user=user.address, signer=agent.key.hex(), public=True
  )
  authenticated = sdk.aster(private)
  assert isinstance(authenticated, AsterMarket)
  assert authenticated.client.futures.client.credentials is not None


async def test_unsupported_methods_raise_instead_of_returning_empty_data():
  """Blocked mappings must not look like implemented support."""
  venue = AsterMarket.new(public=True, mainnet=False)
  perp = PerpMarket(shared=venue.shared, symbol='ASTERUSDT')
  spot = SpotMarket(shared=venue.shared, symbol='ASTERUSDT')
  now = datetime.now(timezone.utc)
  for method in (
    spot.position,
    spot.collateral,
    spot.available_notional,
    perp.available_notional,
    perp.perp_collateral,
  ):
    with pytest.raises(NotImplementedError):
      await method()
  with pytest.raises(NotImplementedError, match='trade history'):
    spot.trades_history(now, now)
  with pytest.raises(NotImplementedError, match='funding payments'):
    perp.funding_payments(now, now)
  for exchange in (venue.spot, venue.perp):
    with pytest.raises(NotImplementedError, match='Exchange-wide'):
      await exchange.trades_history(None, now, now)
  with pytest.raises(NotImplementedError, match='Exchange-wide'):
    await venue.perp.funding_payments(None, now, now)
  with pytest.raises(NotImplementedError, match='snapshots'):
    await Report.new(public=True, mainnet=False).snapshot()
