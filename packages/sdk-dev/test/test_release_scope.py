"""Release scope accounts for complete history and narrowly excludes gateway changes."""

from pathlib import Path
import subprocess

import pytest

from sdk_dev.release_scope import affected_venues, normalized_input, relevant_path
from sdk_dev import evidence


def commit(root: Path):
  """Commit a candidate fixture without external Git configuration."""
  subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, capture_output=True)
  subprocess.run(
    [
      'git',
      '-C',
      str(root),
      '-c',
      'user.name=Test',
      '-c',
      'user.email=test@example.org',
      'commit',
      '-qm',
      'fixture',
    ],
    check=True,
  )


@pytest.fixture
def history(tmp_path: Path) -> Path:
  """Create a prior release and a clean version-only candidate."""
  subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
  project = tmp_path / 'packages/sdk/pkg/pyproject.toml'
  project.parent.mkdir(parents=True)
  project.write_text('[project]\nname="tribulnation-sdk"\nversion="1.0"\n')
  commit(tmp_path)
  subprocess.run(['git', '-C', str(tmp_path), 'tag', 'sdk-v1.0'], check=True)
  project.write_text(project.read_text().replace('1.0', '1.1'))
  commit(tmp_path)
  return tmp_path


def add(root: Path, name: str):
  """Add and commit one release input."""
  path = root / name
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text('changed\n')
  commit(root)


@pytest.mark.parametrize(
  ('name', 'expected'),
  [
    ('packages/sdk/pkg/src/tribulnation/sdk/gateway/server.py', []),
    ('packages/sdk/test/gateway/test_proxy.py', []),
    ('docs/gateway.md', []),
    ('packages/impl/binance/pkg/src/adapter.py', ['binance']),
    ('packages/impl/binance/impl.toml', ['binance']),
    ('packages/impl/binance/test/test_adapter.py', ['binance']),
    ('packages/sdk/pkg/src/tribulnation/sdk/core/sdk.py', ['binance', 'mexc']),
    ('packages/sdk-dev/pkg/src/sdk_dev/evidence.py', []),
    ('packages/sdk-dev/pkg/src/sdk_dev/release_scope.py', []),
    ('packages/sdk-dev/test/test_read_evidence.py', []),
    ('packages/sdk-dev/pkg/src/sdk_dev/read_evidence.py', ['binance', 'mexc']),
    ('packages/sdk-dev/pkg/src/sdk_dev/consistency.py', ['binance', 'mexc']),
    (
      'packages/sdk-dev/pkg/src/sdk_dev/integration/market/public.py',
      ['binance', 'mexc'],
    ),
    ('requirements.txt', ['binance', 'mexc']),
  ],
)
def test_release_impact(history: Path, name: str, expected: list[str]):
  """Only changes relevant to a venue require its live qualification."""
  add(history, name)
  assert affected_venues(history, 'sdk', ['binance', 'mexc']) == expected


def test_earlier_changes_cannot_hide_behind_gateway_release(history: Path):
  """Compare against the published tag, not the release PR's immediate base."""
  add(history, 'packages/sdk/pkg/src/tribulnation/sdk/core/sdk.py')
  add(history, 'packages/sdk/pkg/src/tribulnation/sdk/gateway/server.py')
  assert affected_venues(history, 'sdk', ['binance']) == ['binance']


def test_first_release_requires_all_and_dirty_tree_rejected(history: Path):
  """Missing baselines qualify all; local edits cannot silently bypass the gate."""
  assert affected_venues(history, 'sdk', ['binance']) == []
  (history / 'requirements.txt').write_text('changed')
  with pytest.raises(ValueError, match='clean checkout'):
    affected_venues(history, 'sdk', ['binance'])
  (history / 'requirements.txt').unlink()
  subprocess.run(
    ['git', '-C', str(history), 'tag', '-d', 'sdk-v1.0'],
    check=True,
    capture_output=True,
  )
  assert affected_venues(history, 'sdk', ['binance']) == ['binance']


def test_packaging_normalization_is_narrow():
  """Version and gateway wiring are irrelevant; core requirements remain relevant."""
  name = 'packages/sdk/pkg/pyproject.toml'
  before = b'[project]\nname="tribulnation-sdk"\nversion="1.0"\n[project.optional-dependencies]\na=["venue"]\n'
  after = (
    before.replace(b'1.0', b'1.1')
    + b'gateway=["aiohttp"]\n[project.entry-points."tribulnation.commands"]\ngateway="tribulnation.sdk.gateway.cli:app"\n'
  )
  assert normalized_input(name, before) == normalized_input(name, after)
  assert normalized_input(name, before) != normalized_input(
    name, before.replace(b'name=', b'dependencies=["new-runtime"]\nname=')
  )
  assert (
    normalized_input('requirements.txt', b'-e packages/sdk/pkg[gateway]\n')
    == b'-e packages/sdk/pkg\n'
  )
  assert relevant_path(
    'packages/sdk/pkg/src/tribulnation/sdk/gateway_helpers.py', 'binance'
  )


def test_gateway_files_do_not_change_candidate_digest(tmp_path: Path):
  """Fingerprints and release impact agree on the same source boundary."""
  for package in evidence.package_roots(tmp_path, 'binance').values():
    for folder in (package / 'src', package.parent / 'test'):
      folder.mkdir(parents=True)
      (folder / 'code.py').write_text('value=1')
    (package / 'pyproject.toml').write_text('[project]\nversion="1"\n')
  (tmp_path / 'packages/impl/binance/impl.toml').write_text('')
  before = evidence.candidate_digest(tmp_path, 'binance')
  gateway = tmp_path / 'packages/sdk/pkg/src/tribulnation/sdk/gateway/server.py'
  gateway.parent.mkdir(parents=True)
  gateway.write_text('gateway')
  project = tmp_path / 'packages/sdk/pkg/pyproject.toml'
  project.write_text('[project]\nversion="2"\n')
  assert evidence.candidate_digest(tmp_path, 'binance') == before


def test_deleting_or_moving_core_code_still_requires_evidence(history: Path):
  """Moving relevant code into an excluded directory cannot hide its removal."""
  name = 'packages/sdk/pkg/src/tribulnation/sdk/core.py'
  add(history, name)
  subprocess.run(
    ['git', '-C', str(history), 'tag', '-f', 'sdk-v1.0'],
    check=True,
    capture_output=True,
  )
  target = history / 'packages/sdk/pkg/src/tribulnation/sdk/gateway/core.py'
  target.parent.mkdir(parents=True)
  (history / name).rename(target)
  commit(history)
  assert affected_venues(history, 'sdk', ['binance']) == ['binance']


def test_shallow_history_fails_closed(history: Path):
  """An incomplete clone cannot claim that relevant earlier changes do not exist."""
  head = subprocess.check_output(['git', '-C', str(history), 'rev-parse', 'HEAD'])
  (history / '.git/shallow').write_bytes(head)
  with pytest.raises(ValueError, match='complete history'):
    affected_venues(history, 'sdk', ['binance'])


def test_catalogue_checkout_does_not_block_scope(history: Path):
  """CI's independent Catalogue checkout is not an uncommitted SDK input."""
  folder = history / 'release-catalogue'
  folder.mkdir()
  (folder / 'data.json').write_text('{}')
  assert affected_venues(history, 'sdk', ['binance']) == []


def test_mixed_results_module_keeps_live_behavior_in_scope():
  """Offline commands do not affect observations; runner and import changes do."""
  name = 'packages/sdk-dev/pkg/src/sdk_dev/cli/results.py'
  before = b'def test_surfaces():\n  collect()\n\ndef verify_one():\n  verify()\n'
  assert normalized_input(name, before) == normalized_input(
    name,
    before.replace(b'  verify()', b'  stricter_verify()')
    + b'\ndef release_scope():\n  scope()\n',
  )
  assert normalized_input(name, before) != normalized_input(
    name, before.replace(b'  collect()', b'  collect_other_cases()')
  )
  assert normalized_input(name, before) != normalized_input(
    name, b'import new_runtime\n' + before
  )


def test_command_provider_dependency_is_not_a_venue_dependency():
  """Adding CLI discovery leaves SDK runtime requirements otherwise unchanged."""
  name = 'packages/sdk/pkg/pyproject.toml'
  before = b'[project]\ndependencies=["typed-core>=1"]\n'
  after = b'[project]\ndependencies=["typed-core>=1", "tribulnation-cli>=0.1.0,<1"]\n'
  assert normalized_input(name, before) == normalized_input(name, after)
  assert normalized_input(name, before) != normalized_input(
    name, after.replace(b'typed-core>=1', b'typed-core>=2')
  )


def test_sdk_release_reuses_published_adapter_baseline(history: Path):
  """Already shipped adapter changes need no rerun; later changes still do."""
  project = history / 'packages/impl/binance/pkg/pyproject.toml'
  project.parent.mkdir(parents=True)
  project.write_text('[project]\nversion="1.0"\n')
  name = 'packages/impl/binance/pkg/src/adapter.py'
  add(history, name)
  subprocess.run(['git', '-C', str(history), 'tag', 'binance-v1.0'], check=True)
  assert affected_venues(history, 'sdk', ['binance', 'mexc']) == []
  (history / name).write_text('new behavior\n')
  commit(history)
  assert affected_venues(history, 'sdk', ['binance', 'mexc']) == ['binance']
  add(history, 'packages/sdk/pkg/src/tribulnation/sdk/core.py')
  assert affected_venues(history, 'sdk', ['binance', 'mexc']) == ['binance', 'mexc']


def test_impl_release_cannot_use_its_candidate_tag_as_baseline(history: Path):
  """Only SDK aggregation can reuse an adapter's current published version."""
  project = history / 'packages/impl/binance/pkg/pyproject.toml'
  project.parent.mkdir(parents=True)
  project.write_text('[project]\nversion="1.0"\n')
  commit(history)
  subprocess.run(['git', '-C', str(history), 'tag', 'binance-v1.0'], check=True)
  project.write_text('[project]\nversion="1.1"\n')
  add(history, 'packages/impl/binance/pkg/src/adapter.py')
  subprocess.run(['git', '-C', str(history), 'tag', 'binance-v1.1'], check=True)
  assert affected_venues(history, 'binance', ['binance']) == ['binance']
