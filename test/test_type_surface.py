"""
Guard the generated Typed Client type names this SDK imports.

`impl/**` reaches into per-endpoint generated modules for their type names — e.g.
`from mexc.spot.account.trades import AccountTrade`. Those names come out of the
clients' codegen, so a rename upstream breaks this SDK at import time.

`sdk_type_surface.json` records the whole surface, extracted by AST-parsing
`impl/`. This suite imports every listed module and asserts every listed symbol
resolves, against whatever client versions this environment installs — which
catches breakage from *published* releases, complementing the identical check that
typed-dev runs against its unpublished working tree.

The contract is generated in the workspace by `python3 scripts/sync.py
type-surface`, which writes this copy and typed-dev's together so they cannot
drift. The copy is committed here because this repo is cloned standalone.

A client that is not installed is skipped by name rather than passing, so a missing
package can never look like a verified one. Run with `-rs` to see those reasons.
"""
from functools import cache
from pathlib import Path
import importlib
import json
import pytest
from typing_extensions import TypedDict

CONTRACT = Path(__file__).resolve().parent / 'sdk_type_surface.json'
"""The committed type-surface contract, mirrored from typed-dev."""

class Contract(TypedDict):
  """The committed type-surface contract."""
  comment: str
  source: str
  clients: list[str]
  modules: dict[str, list[str]]

def load_contract() -> Contract:
  """Read the committed contract, failing loudly if it is absent."""
  if not CONTRACT.is_file():
    raise RuntimeError(
      f'missing {CONTRACT}; regenerate it with '
      '`python3 scripts/sync.py type-surface` from the workspace root'
    )
  return json.loads(CONTRACT.read_bytes().decode('utf-8'))

contract = load_contract()
MODULES = contract['modules']
"""Client module path mapped to the symbols this SDK imports from it."""
CLIENTS = contract['clients']
"""Typed Client packages this SDK imports from."""

def client_of(module: str) -> str:
  """
  The Typed Client a dotted module path belongs to.

  Args:
    module: Absolute dotted module path, e.g. `mexc.spot.account.trades`.
  """
  return module.split('.', 1)[0]

@cache
def unavailable(client: str) -> str | None:
  """
  Reason `client` cannot be verified here, or `None` when it imports fine.

  Args:
    client: Top-level client package name.
  """
  try:
    importlib.import_module(client)
  except ImportError as exc:
    return (
      f'UNVERIFIED: type surface of client {client!r} was not checked — {exc}. '
      f'Install typed-{client} in this environment to cover it.'
    )
  return None

def resolves(module: str, symbol: str) -> bool:
  """
  Whether `from <module> import <symbol>` would succeed.

  Mirrors the interpreter's own fallback: a name missing as an attribute may still
  be a submodule that nothing has imported yet.

  Args:
    module: Absolute dotted module path.
    symbol: Name this SDK imports from it.
  """
  if hasattr(importlib.import_module(module), symbol):
    return True
  try:
    importlib.import_module(f'{module}.{symbol}')
  except ImportError:
    return False
  return True

def test_contract_is_populated() -> None:
  """The contract is non-empty, so an empty file cannot pass the suite vacuously."""
  assert MODULES, f'{CONTRACT} lists no modules'
  assert CLIENTS, f'{CONTRACT} lists no clients'

@pytest.mark.parametrize('client', CLIENTS)
def test_client_verifiable(client: str) -> None:
  """Each contracted client is installed here, or is skipped by name."""
  reason = unavailable(client)
  if reason is not None:
    pytest.skip(reason)

@pytest.mark.parametrize('module', sorted(MODULES))
def test_module_exports_contracted_symbols(module: str) -> None:
  """Every symbol this SDK imports from a client module still resolves."""
  reason = unavailable(client_of(module))
  if reason is not None:
    pytest.skip(reason)
  try:
    importlib.import_module(module)
  except ImportError as exc:
    pytest.fail(
      f'{module} is imported by impl/ but is no longer importable: {exc}. '
      'A moved or renamed generated module breaks this SDK.'
    )
  missing = [symbol for symbol in MODULES[module] if not resolves(module, symbol)]
  assert not missing, (
    f'{module} no longer provides {", ".join(missing)}. '
    'impl/ imports these generated names from the installed client. '
    'Either pin a client version that still provides them, or update impl/ and '
    'regenerate the contract with `python3 scripts/sync.py type-surface`.'
  )
