"""Check public venue metadata against packaged implementations and support claims."""

from pathlib import Path
import tomllib

from sdk_dev.registry import load_registry


ROOT = Path(__file__).resolve().parents[3]


def test_registry_links_match_released_implementation_packages():
  """Each released implementation keeps its actual package and source links."""
  registry = load_registry(str(ROOT / 'registry.toml'))
  for release in (ROOT / 'packages/impl').glob('*/RELEASE.md'):
    venue = release.parent.name
    with (release.parent / 'pkg/pyproject.toml').open('rb') as source:
      package = tomllib.load(source)['project']['name']
    entry = registry[venue]
    assert entry['repo'] == 'https://github.com/tribulnation/sdk'
    assert entry['path'] == f'packages/impl/{venue}'
    assert entry['pypi'] == f'https://pypi.org/project/{package}/'


def test_kucoin_and_deribit_public_expansion_preserves_private_surface_scope():
  """Published venue visibility remains separate from per-surface support."""
  registry = load_registry(str(ROOT / 'registry.toml'))
  for venue in ('kucoin', 'deribit'):
    assert registry[venue]['tier'] == 'production'
    assert registry[venue]['icon']
    with (ROOT / f'packages/impl/{venue}/impl.toml').open('rb') as source:
      support = tomllib.load(source)['support']
    assert support['market']['support'] == 'partial'
    assert support['market']['auth'] is False
    assert 'candles' in support['market']['methods']
    assert 'place_order' not in support['market']['methods']
    if venue == 'deribit':
      assert 'rules' not in support['market']['methods']
      assert 'next_funding' not in support['market']['methods']
      assert 'funding_rates' not in support['market']['methods']
    assert support['report']['support'] == 'partial'
    assert support['earn']['support'] == 'partial'
