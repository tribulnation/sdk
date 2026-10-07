"""Tests for the TOML-based account-loading mechanism."""

from pathlib import Path
import pytest

from tribulnation.sdk.impl.accounts import Dydx, Hyperliquid, load_accounts
from tribulnation.sdk.impl.market import MarketSDK

TOML = """
[accounts.hl]
venue       = "hyperliquid"
address     = "$HYPERLIQUID_ADDRESS"
private_key = "$HYPERLIQUID_PRIVATE_KEY"

[accounts.dydx]
venue    = "dydx"
address  = "$DYDX_ADDRESS"
mnemonic = "$DYDX_MNEMONIC"
"""


def _write_toml(tmp_path: Path, contents: str = TOML) -> Path:
  path = tmp_path / 'sdk.toml'
  path.write_text(contents)
  return path


def test_load_accounts_parses_discriminated_union(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  """`load_accounts` resolves each `[accounts.<id>]` table to its venue-specific dataclass."""
  monkeypatch.setenv('HYPERLIQUID_ADDRESS', '0xabc')
  monkeypatch.setenv('HYPERLIQUID_PRIVATE_KEY', '0xdef')
  monkeypatch.setenv('DYDX_ADDRESS', 'dydx1abc')
  monkeypatch.setenv('DYDX_MNEMONIC', 'word ' * 12)

  path = _write_toml(tmp_path)
  accounts = load_accounts(path)

  assert set(accounts) == {'hl', 'dydx'}
  hl = accounts['hl']
  assert isinstance(hl, Hyperliquid)
  assert hl.resolved_address == '0xabc'
  assert hl.resolved_private_key == '0xdef'

  dydx = accounts['dydx']
  assert isinstance(dydx, Dydx)
  assert dydx.resolved_address == 'dydx1abc'
  assert dydx.resolved_creds == {'mnemonic': 'word ' * 12, 'private_key': None}


def test_load_accounts_fails_fast_on_missing_env_var(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  """A required env var left unset raises eagerly, at load time, not on first use."""
  monkeypatch.delenv('HYPERLIQUID_ADDRESS', raising=False)
  monkeypatch.delenv('HYPERLIQUID_PRIVATE_KEY', raising=False)

  path = _write_toml(
    tmp_path,
    """
[accounts.hl]
venue = "hyperliquid"
""",
  )

  with pytest.raises(ValueError, match='HYPERLIQUID_ADDRESS'):
    load_accounts(path)


def test_load_accounts_missing_file_raises(tmp_path: Path) -> None:
  """A path that does not exist raises `ValueError` rather than returning defaults."""
  with pytest.raises(ValueError, match='not found'):
    load_accounts(tmp_path / 'does-not-exist.toml')


def test_market_sdk_load_constructs_from_toml(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  """`MarketSDK.load` builds an SDK instance whose `accounts` come from the TOML file."""
  monkeypatch.setenv('HYPERLIQUID_ADDRESS', '0xabc')
  monkeypatch.setenv('HYPERLIQUID_PRIVATE_KEY', '0xdef')
  monkeypatch.setenv('DYDX_ADDRESS', 'dydx1abc')
  monkeypatch.setenv('DYDX_MNEMONIC', 'word ' * 12)

  path = _write_toml(tmp_path)
  sdk = MarketSDK.load(path)

  assert set(sdk.accounts) == {'hl', 'dydx'}
  assert isinstance(sdk.accounts['hl'], Hyperliquid)


async def test_dydx_api_wallet_account_signs_for_its_address() -> None:
  """A dYdX API wallet key with an account address signs for that account."""
  from tribulnation.dydx import DydxMarket

  account = 'dydx1039f5sxkl0t39vxcsnmlu62ly22typdap0zkyn'
  sdk = MarketSDK({'dydx': Dydx(address=account, private_key='0x' + '11' * 32)})
  venue = await sdk.venue('dydx')
  assert isinstance(venue, DydxMarket)
  wallet = venue.shared.client.node.require_wallet()
  assert venue.shared.address == account
  assert wallet.address == account
  assert wallet.is_api_wallet


def test_dydx_account_requires_an_address(monkeypatch: pytest.MonkeyPatch) -> None:
  """A non-public dYdX account fails fast without an address, even with a key."""
  monkeypatch.delenv('DYDX_ADDRESS', raising=False)
  with pytest.raises(ValueError, match='DYDX_ADDRESS'):
    Dydx(private_key='0x' + '11' * 32).verify_env_vars()
