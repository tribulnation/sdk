"""CI package selection excludes sketches and covers SDK development tooling."""

from pathlib import Path
import runpy
from typing_extensions import Callable, cast

import pytest

select_packages = cast(
  Callable[[Path, list[str]], list[str]],
  runpy.run_path(
    str(Path(__file__).resolve().parents[3] / '.github' / 'select_packages.py')
  )['select_packages'],
)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
  """A small checkout with two installable implementations and one PoC."""
  for name in ('sdk', 'sdk-dev', 'impl/bybit', 'impl/mexc'):
    package = tmp_path / 'packages' / name / 'pkg'
    package.mkdir(parents=True)
    (package / 'pyproject.toml').touch()
  (tmp_path / 'packages' / 'impl' / 'kucoin' / 'poc').mkdir(parents=True)
  return tmp_path


def test_sdk_change_selects_only_buildable_packages(repository: Path):
  """Base contracts fan out to every real package, never a PoC-only directory."""
  assert select_packages(repository, ['packages/sdk/pkg/src/base.py']) == [
    'bybit',
    'mexc',
    'sdk',
    'sdk-dev',
  ]


def test_changed_poc_does_not_create_an_install_job(repository: Path):
  """A sketch has no package manifest and cannot be installed."""
  assert select_packages(repository, ['packages/impl/kucoin/poc/market.py']) == []


def test_venue_change_selects_only_that_package(repository: Path):
  """Venue code or support declarations affect that implementation's job."""
  assert select_packages(repository, ['packages/impl/bybit/impl.toml']) == ['bybit']


def test_sdk_dev_changes_are_checked(repository: Path):
  """Internal tooling changes must run a package job and the unit suite."""
  assert select_packages(repository, ['packages/sdk-dev/pkg/src/cli.py']) == ['sdk-dev']


def test_workflow_changes_check_every_package(repository: Path):
  """CI edits exercise the full package matrix."""
  assert select_packages(repository, ['.github/workflows/check.yml']) == [
    'bybit',
    'mexc',
    'sdk',
    'sdk-dev',
  ]
