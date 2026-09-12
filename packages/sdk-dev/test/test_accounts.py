"""Generated documentation account configurations match actual SDK dataclasses."""

from pathlib import Path
import tomllib

import pydantic
import pytest

from sdk_dev.accounts import generate_accounts_toml
from sdk_dev.registry import load_registry
from tribulnation.sdk.impl.accounts import Account, load_accounts


def test_account_examples_cover_every_registered_implementation():
  """All twelve packages have both credential and explicit-public TOML blocks."""
  root = Path(__file__).resolve().parents[3]
  venues = set(load_registry(str(root / 'registry.toml')))
  assert set(generate_accounts_toml()) == venues
  assert set(generate_accounts_toml(public=True)) == venues


def test_public_accounts_load_without_credentials(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
  """Explicit public accounts parse and resolve without credentials or network calls."""
  monkeypatch.setattr('os.environ', {})
  blocks = generate_accounts_toml(public=True)
  path = tmp_path / 'sdk.toml'
  path.write_text('\n\n'.join(blocks.values()))
  accounts = load_accounts(path)
  assert set(accounts) == set(blocks)
  for account in accounts.values():
    assert account.public
    account.verify_env_vars()
  deribit = accounts['deribit']
  assert deribit.venue == 'deribit'
  assert deribit.resolved_client_id is None
  assert deribit.resolved_client_secret is None


def test_credential_blocks_use_valid_fields_and_explicit_deribit_defaults():
  """Credential examples remain parseable, including Deribit's property defaults."""
  blocks = generate_accounts_toml()
  raw = tomllib.loads('\n\n'.join(blocks.values()))['accounts']
  accounts = pydantic.TypeAdapter(dict[str, Account]).validate_python(raw)
  assert not any(account.public for account in accounts.values())
  assert raw['deribit']['client_id'] == '$DERIBIT_CLIENT_ID'
  assert raw['deribit']['client_secret'] == '$DERIBIT_CLIENT_SECRET'
