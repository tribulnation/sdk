"""Account routing, credential isolation and explicit qualification gaps."""

from pathlib import Path
from eth_account import Account
import pytest
from tribulnation.aster import AsterMarket, Earn, Report, Wallet
from tribulnation.sdk import EarnSDK, MarketSDK, ReportSDK, WalletSDK
from tribulnation.sdk.impl.accounts import Aster, load_accounts


def test_testnet_credentials_do_not_fall_back_to_mainnet(
  monkeypatch: pytest.MonkeyPatch,
):
  """Mainnet keys, including the main-wallet key, cannot leak into testnet clients."""
  monkeypatch.setenv('ASTER_USER', Account.create().address)
  monkeypatch.setenv('ASTER_SIGNER_PRIVATE_KEY', Account.create().key.hex())
  monkeypatch.setenv('ASTER_USER_PRIVATE_KEY', Account.create().key.hex())
  monkeypatch.setenv('ASTER_SIGNER', Account.create().address)
  monkeypatch.delenv('TEST_ASTER_USER', raising=False)
  monkeypatch.delenv('TEST_ASTER_SIGNER_PRIVATE_KEY', raising=False)
  with pytest.raises(ValueError, match='TEST_ASTER_USER'):
    Aster(venue='aster_testnet').verify_env_vars()
  from tribulnation.sdk import AuthError

  with pytest.raises(AuthError, match='TEST_ASTER_USER'):
    AsterMarket.new(mainnet=False)
  user, agent = Account.create(), Account.create()
  venue = AsterMarket.new(mainnet=False, user=user.address, signer=agent.key.hex())
  credentials = venue.client.futures.client.credentials
  assert credentials is not None and credentials.user == user.address
  assert credentials.agent is not None and credentials.agent.address == agent.address
  assert credentials.main is None
  assert venue.client.spot.client.credentials is credentials
  assert venue.client.chain.client.credentials is None


async def test_toml_routes_both_networks_and_preserves_explicit_public_credentials(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
  """TOML discrimination, optional installation routes and resource sharing agree."""
  monkeypatch.setattr('os.environ', {})
  path = tmp_path / 'sdk.toml'
  path.write_text(
    '[accounts.main]\nvenue="aster"\npublic=true\n[accounts.test]\nvenue="aster_testnet"\npublic=true\n'
  )
  accounts = load_accounts(path)
  sdk = MarketSDK(accounts=accounts)
  async with sdk:
    venue = await sdk.venue('test')
    assert venue is await sdk.venue('test')
    assert venue.venue_id == 'aster_testnet'
    assert [r['id'] for r in await venue.exchanges()] == ['spot', 'perp']
    assert await venue.perp_exchange('perp') is await venue.exchange('perp')
    with pytest.raises(ValueError, match='perpetual exchange'):
      await venue.perp_exchange('spot')
    assert (await sdk.venue('main')).venue_id == 'aster'
    with pytest.raises(ValueError, match='Unknown Aster exchange'):
      await venue.exchange('inverse')
  assert isinstance(ReportSDK(accounts=accounts).venue('test'), Report)
  assert isinstance(WalletSDK(accounts=accounts).venue('test'), Wallet)
  assert isinstance(EarnSDK(accounts=accounts).venue('test'), Earn)
  user, agent = Account.create(), Account.create()
  private = Aster(
    venue='aster_testnet', user=user.address, signer=agent.key.hex(), public=True
  )
  authenticated = sdk.aster(private)
  assert isinstance(authenticated, AsterMarket)
  assert authenticated.client.futures.client.credentials is not None


async def test_unqualified_methods_fail_instead_of_returning_empty_data():
  """Empty or blocked PoC methods must not look like implemented SDK support."""
  venue = AsterMarket.new(mainnet=False, public=True)
  from tribulnation.aster.market.market import PerpMarket, SpotMarket

  perp = PerpMarket(exchange=venue.perp, symbol='ASTERUSDT')
  spot = SpotMarket(exchange=venue.spot, symbol='ASTERUSDT')
  from datetime import datetime, timezone

  now = datetime.now(timezone.utc)
  for method in (
    spot.position,
    spot.collateral,
    perp.available_notional,
    perp.perp_collateral,
    venue.perp.perp_stats,
  ):
    with pytest.raises(NotImplementedError):
      await method()
  with pytest.raises(NotImplementedError, match='nonzero'):
    await perp.funding_payments(now, now)
  for market in (spot, perp):
    with pytest.raises(NotImplementedError):
      await market.trades_history(now, now)
    with pytest.raises(NotImplementedError, match='exchange-wide'):
      await market.exchange.trades_history(None, now, now)
  with pytest.raises(NotImplementedError, match='exchange-wide'):
    await venue.perp.funding_payments(None, now, now)
  with pytest.raises(NotImplementedError, match='funded balances'):
    await Report.new(public=True, mainnet=False).snapshot()
  with pytest.raises(NotImplementedError, match='catalogues'):
    await Wallet.new(public=True).deposit_methods()
  with pytest.raises(NotImplementedError, match='catalogue'):
    await Earn.new(public=True).instruments()
