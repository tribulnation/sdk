"""Offline evidence detects content drift without trusting commit identifiers."""

from datetime import datetime, timedelta, timezone
from importlib import metadata
import json
from pathlib import Path
from os import PathLike
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sdk_dev import evidence


@pytest.fixture
def candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
  """Create isolated candidate trees and a deterministic installed-dependency set."""
  root = tmp_path / 'sdk'
  for package in evidence.package_roots(root, 'binance').values():
    for folder in (package / 'src', package.parent / 'test'):
      folder.mkdir(parents=True)
      (folder / 'code.py').write_text('value = 1\n')
    (package / 'pyproject.toml').write_text('[project]\nname="example"\n')
  (root / 'packages/impl/binance/impl.toml').write_text(
    '[support.market]\nsupport="partial"\n'
  )
  catalogue = tmp_path / 'catalogue'
  catalogue.mkdir()
  (catalogue / 'markets.json').write_text('{"BTC": "bitcoin"}\n')
  monkeypatch.setattr(
    evidence,
    'installed_dependencies',
    Mock(
      return_value={
        'example-package': evidence.Dependency(
          version='1.2.3',
          metadata_sha256='a' * 64,
          files_sha256='b' * 64,
        ),
      }
    ),
  )
  return root, catalogue


def report(root: Path, catalogue: Path, output: Path) -> evidence.Snapshot:
  """Write a minimal completed public result using current candidate content."""
  snapshot = evidence.capture(root, 'binance', catalogue)
  now = datetime.now(timezone.utc)
  evidence.write_report(
    output,
    before=snapshot,
    after=snapshot,
    payload={'venue': 'binance', 'checks': [{'status': 'passed', 'id': 'identity'}]},
    started=now - timedelta(seconds=1),
    finished=now,
  )
  return snapshot


def test_roundtrip_and_external_pins(candidate: tuple[Path, Path], tmp_path: Path):
  """Public results survive independent verification and produce reproducible pins."""
  root, catalogue = candidate
  output = tmp_path / 'report'
  report(root, catalogue, output)
  assert evidence.verify_report(root, output, catalogue)['venue'] == 'binance'
  assert (output / 'dependency-pins.txt').read_text() == 'example-package==1.2.3\n'


@pytest.mark.parametrize(
  'filename', ['results.json', 'summary.md', 'dependency-pins.txt']
)
def test_report_tampering_fails(
  candidate: tuple[Path, Path],
  tmp_path: Path,
  filename: str,
):
  """Changing any persisted result, summary or pin invalidates the report."""
  root, catalogue = candidate
  output = tmp_path / 'report'
  report(root, catalogue, output)
  path = output / filename
  path.write_text(path.read_text() + '\n')
  with pytest.raises(ValueError, match='modified'):
    evidence.verify_report(root, output, catalogue)


@pytest.mark.parametrize('field', ['source', 'test', 'support', 'catalogue'])
def test_candidate_content_drift_fails(
  candidate: tuple[Path, Path],
  tmp_path: Path,
  field: str,
):
  """Relevant code, tests, support and Catalogue edits invalidate prior evidence."""
  root, catalogue = candidate
  output = tmp_path / 'report'
  report(root, catalogue, output)
  paths = {
    'source': root / 'packages/sdk/pkg/src/code.py',
    'test': root / 'packages/sdk-dev/test/code.py',
    'support': root / 'packages/impl/binance/impl.toml',
    'catalogue': catalogue / 'markets.json',
  }
  paths[field].write_text('changed\n')
  with pytest.raises(ValueError, match='does not match current'):
    evidence.verify_report(root, output, catalogue)


def test_dependency_drift_fails(
  candidate: tuple[Path, Path],
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
):
  """Identical versions with changed installed source still invalidate evidence."""
  root, catalogue = candidate
  output = tmp_path / 'report'
  report(root, catalogue, output)
  monkeypatch.setattr(
    evidence,
    'installed_dependencies',
    Mock(
      return_value={
        'example-package': evidence.Dependency(
          version='1.2.3',
          metadata_sha256='a' * 64,
          files_sha256='c' * 64,
        ),
      }
    ),
  )
  with pytest.raises(ValueError, match='does not match current'):
    evidence.verify_report(root, output, catalogue)


def test_unrelated_docs_credentials_and_reports_do_not_drift(
  candidate: tuple[Path, Path],
  tmp_path: Path,
):
  """No git SHA, secret account file, documentation or report tree is fingerprinted."""
  root, catalogue = candidate
  output = root / 'release-evidence/binance'
  report(root, catalogue, output)
  (root / 'sdk.test.toml').write_text('secret = "not-read"\n')
  (root / '.env').write_text('SECRET=not-read\n')
  (root / 'README.md').write_text('changed docs\n')
  (root / '.git').mkdir()
  (root / '.git/HEAD').write_text('changed commit\n')
  assert evidence.verify_report(root, output, catalogue)['venue'] == 'binance'


def test_changed_inputs_prevent_writing(candidate: tuple[Path, Path], tmp_path: Path):
  """A run edited while executing cannot leave apparently valid evidence."""
  root, catalogue = candidate
  before = evidence.capture(root, 'binance', catalogue)
  (catalogue / 'markets.json').write_text('{}\n')
  after = evidence.capture(root, 'binance', catalogue)
  now = datetime.now(timezone.utc)
  output = tmp_path / 'report'
  with pytest.raises(ValueError, match='changed during'):
    evidence.write_report(
      output,
      before=before,
      after=after,
      payload={'venue': 'binance'},
      started=now,
      finished=now,
    )
  assert not output.exists()


def test_existing_reports_are_never_overwritten(
  candidate: tuple[Path, Path], tmp_path: Path
):
  """A pre-existing evidence directory belongs to the maintainer."""
  root, catalogue = candidate
  output = tmp_path / 'report'
  report(root, catalogue, output)
  original = (output / 'manifest.json').read_bytes()
  with pytest.raises(FileExistsError):
    report(root, catalogue, output)
  assert (output / 'manifest.json').read_bytes() == original


@pytest.mark.parametrize(
  'change', ['expiry', 'future', 'naive', 'venue', 'schema', 'before_after']
)
def test_invalid_manifest_fails(
  candidate: tuple[Path, Path], tmp_path: Path, change: str
):
  """Malformed, expired, cross-venue and inconsistent reports fail closed."""
  root, catalogue = candidate
  output = tmp_path / 'report'
  report(root, catalogue, output)
  path = output / 'manifest.json'
  manifest = json.loads(path.read_text())
  if change == 'expiry':
    manifest['started'] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
  elif change == 'future':
    manifest['finished'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
  elif change == 'naive':
    manifest['started'] = '2026-09-10T00:00:00'
  elif change == 'venue':
    manifest['before']['venue'] = manifest['after']['venue'] = 'mexc'
  elif change == 'schema':
    manifest['schema_version'] = 99
  else:
    manifest['after']['source_sha256'] = 'f' * 64
  path.write_text(json.dumps(manifest))
  with pytest.raises(ValueError):
    evidence.verify_report(root, output, catalogue)


@pytest.mark.parametrize(
  'payload', [{'venue': 'mexc'}, {'venue': 'binance', 'exception': 'raw'}]
)
def test_private_or_wrong_venue_payload_rejected(
  candidate: tuple[Path, Path],
  tmp_path: Path,
  payload: dict[str, object],
):
  """Payload boundaries reject obvious secret material and identity mismatches."""
  root, catalogue = candidate
  snapshot = evidence.capture(root, 'binance', catalogue)
  now = datetime.now(timezone.utc)
  with pytest.raises(ValueError):
    evidence.write_report(
      tmp_path / 'report',
      before=snapshot,
      after=snapshot,
      payload=payload,
      started=now,
      finished=now,
    )


class ExampleDistribution(metadata.Distribution):
  """Minimal installed distribution supporting editable/wheel equivalence tests."""

  def __init__(self, root: Path, *, editable: bool):
    """Record actual source location, independent of any candidate checkout."""
    self.root = root
    self.editable = editable

  def read_text(self, filename: str) -> str | None:
    """Supply the installed package's identity and optional editable pointer."""
    if filename == 'METADATA':
      return 'Name: example\nVersion: 1.0\nRequires-Python: >=3.10\n'
    if filename == 'direct_url.json' and self.editable:
      return json.dumps({'url': self.root.as_uri(), 'dir_info': {'editable': True}})
    return None

  def locate_file(self, path: str | PathLike[str]):
    """Resolve installed wheel files relative to their installation location."""
    return self.root / path

  @property
  def files(self) -> list[metadata.PackagePath]:
    """List only the installed executable source file."""
    return [metadata.PackagePath('example/__init__.py')]


def test_actual_editable_source_hash_and_wheel_normalization(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
):
  """The same package source hashes identically across roots and installation modes."""
  editable = tmp_path / 'editable'
  wheel = tmp_path / 'wheel'
  for directory in (editable / 'src/example', wheel / 'example'):
    directory.mkdir(parents=True)
    (directory / '__init__.py').write_text('VALUE = 1\n')
  monkeypatch.setattr(
    evidence.util,
    'find_spec',
    Mock(
      return_value=SimpleNamespace(
        origin=str(editable / 'src/example/__init__.py'),
      )
    ),
  )
  first = evidence.dependency(ExampleDistribution(editable, editable=True))
  monkeypatch.setattr(
    evidence.util,
    'find_spec',
    Mock(
      return_value=SimpleNamespace(
        origin=str(wheel / 'example/__init__.py'),
      )
    ),
  )
  assert first == evidence.dependency(ExampleDistribution(wheel, editable=False))
  (wheel / 'example/__init__.py').write_text('VALUE = 2\n')
  assert first != evidence.dependency(ExampleDistribution(wheel, editable=False))


def test_shadowed_dependency_is_not_fingerprinted(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
):
  """Hashing installed metadata cannot authorize different imported dependency code."""
  source = tmp_path / 'installed/example'
  source.mkdir(parents=True)
  (source / '__init__.py').write_text('VALUE = 1\n')
  monkeypatch.setattr(
    evidence.util,
    'find_spec',
    Mock(
      return_value=SimpleNamespace(
        origin=str(tmp_path / 'shadow/example/__init__.py'),
      )
    ),
  )
  with pytest.raises(ValueError, match='shadowed'):
    evidence.dependency(ExampleDistribution(source.parent, editable=False))


def test_metadata_only_distribution_is_valid(tmp_path: Path):
  """Metapackages have empty code but still bind their installed metadata."""
  info = tmp_path / 'example-1.0.dist-info'
  info.mkdir()
  (info / 'METADATA').write_text(
    'Name: example\nVersion: 1.0\nRequires-Dist: real-code>=1\n'
  )
  (info / 'RECORD').write_text('example-1.0.dist-info/METADATA,,\n')
  dist = metadata.Distribution.at(info)
  first = evidence.dependency(dist)
  assert first.files_sha256 == evidence.digest(evidence.json_bytes({}))
  (info / 'METADATA').write_text(
    'Name: example\nVersion: 1.0\nRequires-Dist: real-code>=2\n'
  )
  assert evidence.dependency(dist) != first


def test_missing_distribution_inventory_is_rejected(tmp_path: Path):
  """Missing RECORD must not masquerade as a legitimate empty metapackage."""
  info = tmp_path / 'example-1.0.dist-info'
  info.mkdir()
  (info / 'METADATA').write_text('Name: example\nVersion: 1.0\n')
  with pytest.raises(ValueError, match='no file inventory'):
    evidence.dependency(metadata.Distribution.at(info))


def test_missing_report_and_symlink_fail(candidate: tuple[Path, Path], tmp_path: Path):
  """Partial reports and substituted files cannot verify."""
  root, catalogue = candidate
  output = tmp_path / 'report'
  with pytest.raises(ValueError, match='missing files'):
    evidence.verify_report(root, output, catalogue)
  report(root, catalogue, output)
  body = output / 'results.json'
  other = tmp_path / 'other.json'
  body.rename(other)
  body.symlink_to(other)
  with pytest.raises(ValueError, match='symlinks'):
    evidence.verify_report(root, output, catalogue)
