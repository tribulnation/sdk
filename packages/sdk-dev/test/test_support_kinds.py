"""Market-kind-aware support declarations (ADR 0056)."""

from pathlib import Path

import pydantic
import pytest

from sdk_dev.repo import repo_root
from sdk_dev.support import (
  ImplFile,
  MarketKind,
  kind_conflicts,
  load_impl_files,
  load_method_kinds,
  load_support_matrix,
  method_universe,
)

KINDS: dict[str, MarketKind | None] = {
  'depth': None,
  'balances': 'spot',
  'leverage': 'perp',
}


def impl(**market: object) -> ImplFile:
  """An impl.toml with one `[support.market]` table."""
  return ImplFile.model_validate({'support': {'market': {'auth': False, **market}}})


def universe(impls: dict[str, ImplFile], method: str) -> list[str]:
  """The eligible venues of one method of `KINDS`."""
  return method_universe(impls, 'market', method, kind=KINDS[method])


def test_full_means_every_method_applicable_to_the_kinds():
  """A `full` venue serves unscoped methods and those of its kinds, no others."""
  impls = {
    'both': impl(support='full'),
    'perp': impl(support='full', kinds=['perp']),
    'spot': impl(support='full', kinds=['spot']),
  }
  assert universe(impls, 'depth') == ['both', 'perp', 'spot']
  assert universe(impls, 'balances') == ['both', 'spot']
  assert universe(impls, 'leverage') == ['both', 'perp']


def test_partial_still_names_its_methods():
  """A `partial` list keeps working, with or without kinds."""
  impls = {
    'listed': impl(support='partial', methods=['depth', 'balances']),
    'none': impl(support='none', methods=['depth']),
  }
  assert universe(impls, 'depth') == ['listed']
  assert universe(impls, 'balances') == ['listed']
  assert universe(impls, 'leverage') == []


def test_kinds_are_validated():
  """Kinds are known, non-empty and unique."""
  for kinds in ([], ['spot', 'spot'], ['option']):
    with pytest.raises(pydantic.ValidationError):
      impl(support='full', kinds=kinds)


def test_conflicting_declarations_are_reported():
  """A partial list naming a method outside the kinds contradicts the contract, and
  kinds on a surface without kind-scoped methods mean nothing."""
  impls = {
    'ok': impl(support='partial', kinds=['perp'], methods=['depth', 'leverage']),
    'bad': impl(support='partial', kinds=['perp'], methods=['balances']),
  }
  assert kind_conflicts(impls, 'market', KINDS) == [
    "bad: market.balances is spot-only, outside kinds ['perp']"
  ]
  assert len(kind_conflicts(impls, 'market', {'depth': None})) == 2


def test_support_matrix_exports_declared_kinds(tmp_path: Path):
  """support.json carries `kinds` only where a venue declares them."""
  for slug, body in (
    ('perp', 'support = "full"\nauth = false\nkinds = ["perp"]\n'),
    ('both', 'support = "full"\nauth = false\n'),
  ):
    (tmp_path / slug).mkdir()
    (tmp_path / slug / 'impl.toml').write_text(f'[support.market]\n{body}')
  venues = load_support_matrix(tmp_path)['market']['venues']
  assert venues['perp'] == {'support': 'full', 'auth': False, 'kinds': ['perp']}
  assert venues['both'] == {'support': 'full', 'auth': False}


def test_committed_declarations_agree_with_the_contracts():
  """No committed impl.toml contradicts a contract's kinds, and every perpetual-only
  venue is `full` without being counted for spot methods."""
  root = repo_root()
  impls = load_impl_files(root / 'packages/impl')
  for contract in sorted((root / 'docs/contract').glob('*.yml')):
    assert kind_conflicts(impls, contract.stem, load_method_kinds(contract)) == []
  kinds = load_method_kinds(root / 'docs/contract/market.yml')
  for venue in ('dydx', 'extended', 'grvt'):
    assert impls[venue].support['market'].support == 'full'
    for method, kind in kinds.items():
      eligible = venue in method_universe(impls, 'market', method, kind=kind)
      assert eligible == (kind != 'spot'), (venue, method)
