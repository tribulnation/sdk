"""Release dependencies retain the SDK contract and transport cleanup fixes."""

from pathlib import Path
from packaging.requirements import Requirement
from packaging.version import Version
import tomllib
from typing_extensions import cast

ROOT = Path(__file__).resolve().parents[3]
COMPATIBLE_IMPLEMENTATIONS = {
  'aster': '0.5.0',
  'binance': '0.3.0',
  'bit2me': '0.5.0',
  'bitget': '0.7.0',
  'bybit': '0.5.0',
  'coinbase': '0.2.0',
  'deribit': '0.3.0',
  'dydx': '0.11.0',
  'ethereum': '0.6.0',
  'hyperliquid': '0.11.0',
  'kraken': '0.2.0',
  'kucoin': '0.3.0',
  'lighter': '0.4.0',
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
    requirements = [Requirement(value) for value in dependencies(manifest)]
    sdk = next(value for value in requirements if value.name == 'tribulnation-sdk')
    floors = [
      Version(value.version) for value in sdk.specifier if value.operator == '>='
    ]
    assert floors and max(floors) >= Version('2.0.0'), manifest


def test_sdk_extras_exclude_pre_migration_implementations():
  """SDK extras must not resolve to older, incompatible venue packages."""
  project = tomllib.loads((ROOT / 'packages/sdk/pkg/pyproject.toml').read_text())
  extras = project['project']['optional-dependencies']
  for venue, version in COMPATIBLE_IMPLEMENTATIONS.items():
    requirement = next(
      Requirement(value)
      for value in extras[venue]
      if Requirement(value).name == f'tribulnation-{venue}'
    )
    floors = [
      Version(value.version)
      for value in requirement.specifier
      if value.operator == '>='
    ]
    assert floors and max(floors) >= Version(version), venue


def test_ethereum_requires_the_renamed_typed_namespace():
  """The published 0.1.x Ethereum client cannot satisfy typed_ethereum imports."""
  assert 'typed-ethereum>=0.2.0' in dependencies(
    ROOT / 'packages/impl/ethereum/pkg/pyproject.toml',
  )


def test_funding_adapters_require_received_positive_sdk():
  """Do not install the cash-flow adapters against the old paid-positive contract."""
  for venue in ('hyperliquid', 'dydx', 'bybit', 'aster', 'lighter'):
    manifest = ROOT / f'packages/impl/{venue}/pkg/pyproject.toml'
    requirement = next(
      Requirement(value)
      for value in dependencies(manifest)
      if Requirement(value).name == 'tribulnation-sdk'
    )
    assert Version('2.9.0') not in requirement.specifier, venue
    assert Version('2.10.0') in requirement.specifier, venue
