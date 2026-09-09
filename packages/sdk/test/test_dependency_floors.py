"""Release dependencies retain the SDK contract and transport cleanup fixes."""

from pathlib import Path
import tomllib
from typing_extensions import cast

ROOT = Path(__file__).resolve().parents[3]
SDK_2_IMPLEMENTATIONS = {
  'binance': '0.3.0',
  'bit2me': '0.5.0',
  'bitget': '0.7.0',
  'bybit': '0.2.0',
  'coinbase': '0.2.0',
  'deribit': '0.2.0',
  'dydx': '0.7.0',
  'ethereum': '0.6.0',
  'hyperliquid': '0.7.0',
  'kraken': '0.2.0',
  'kucoin': '0.2.0',
  'mexc': '2.0.0',
}


def dependencies(path: Path) -> list[str]:
  """Read a package's declared runtime dependencies without importing its code."""
  return cast(list[str], tomllib.loads(path.read_text())['project']['dependencies'])


def test_sdk_requires_fixed_transport_core():
  """Fresh SDK installations must include the cancellation/join fixes."""
  assert 'typed-core>=0.8.1' in dependencies(ROOT / 'packages/sdk/pkg/pyproject.toml')


def test_implementations_require_the_current_sdk_contract():
  """Every packaged implementation excludes pre-SDK-2 base contracts."""
  for manifest in sorted((ROOT / 'packages/impl').glob('*/pkg/pyproject.toml')):
    if manifest.parents[1].name.startswith('.'):
      continue
    assert 'tribulnation-sdk>=2.0.0' in dependencies(manifest), manifest


def test_sdk_extras_exclude_pre_migration_implementations():
  """SDK 2 extras must not resolve to older, incompatible venue packages."""
  project = tomllib.loads((ROOT / 'packages/sdk/pkg/pyproject.toml').read_text())
  extras = project['project']['optional-dependencies']
  for venue, version in SDK_2_IMPLEMENTATIONS.items():
    assert f'tribulnation-{venue}>={version}' in extras[venue], venue


def test_ethereum_requires_the_renamed_typed_namespace():
  """The published 0.1.x Ethereum client cannot satisfy typed_ethereum imports."""
  assert 'typed-ethereum>=0.2.0' in dependencies(
    ROOT / 'packages/impl/ethereum/pkg/pyproject.toml',
  )
