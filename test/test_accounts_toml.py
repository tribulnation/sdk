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
  assert dydx.resolved_mnemonic == 'word ' * 12


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
