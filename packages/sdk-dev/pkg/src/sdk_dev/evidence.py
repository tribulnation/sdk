"""Local release evidence is a seven-day content drift check, not an attestation."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from importlib import metadata, util
import json
from pathlib import Path
import re
import sys
import tomllib
from urllib.parse import unquote, urlparse

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, JsonValue

MAX_AGE = timedelta(days=7)
SKIP_DIRS = frozenset({'.git', '.venv', '__pycache__', '.pytest_cache', '.ruff_cache'})
SENSITIVE_KEYS = frozenset(
  {
    'exception',
    'traceback',
    'headers',
    'credentials',
    'password',
    'secret',
    'api_key',
    'api_secret',
    'private_key',
    'raw_response',
    'account_data',
  }
)


class FrozenModel(BaseModel):
  """Reject unexpected report structure and accidental snapshot mutation."""

  model_config = ConfigDict(extra='forbid', frozen=True, strict=True)


class Dependency(FrozenModel):
  """Installed package identity and portable executable-content checksum."""

  version: str = Field(pattern=r'^[A-Za-z0-9.!+_-]+$')
  metadata_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
  files_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Snapshot(FrozenModel):
  """Relevant candidate, installed dependency, interpreter and Catalogue inputs."""

  schema_version: int = Field(default=1, ge=1, le=1)
  venue: str = Field(pattern=r'^[a-z][a-z0-9_-]*$')
  python: str = Field(pattern=r'^\d+\.\d+$')
  source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
  catalogue_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
  dependencies: dict[str, Dependency] = Field(min_length=1)


class Manifest(FrozenModel):
  """Inputs and timestamps binding a completed run to its public results."""

  schema_version: int = Field(default=1, ge=1, le=1)
  before: Snapshot
  after: Snapshot
  started: datetime
  finished: datetime
  results_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
  summary_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Results(FrozenModel):
  """JSON-only sanitized check output; check inventory is validated by the runner."""

  payload: dict[str, JsonValue]


class EditableInfo(BaseModel):
  """Validate the editable flag without rejecting unrelated installer fields."""

  editable: bool = False


class DirectURL(BaseModel):
  """Read only the documented direct-url fields needed for source provenance."""

  url: str
  dir_info: EditableInfo = Field(default_factory=EditableInfo)


def digest(data: bytes) -> str:
  """Return a stable content checksum."""
  return sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
  """Serialize portable JSON deterministically and reject NaN/infinity."""
  return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def files_digest(files: dict[str, Path]) -> str:
  """Hash file identities and contents, rejecting symlinks and missing inputs."""
  hashes: dict[str, str] = {}
  for name, path in sorted(files.items()):
    if path.is_symlink() or not path.is_file():
      raise ValueError(f'Evidence input is missing or a symlink: {name}')
    hashes[name] = digest(path.read_bytes())
  if not hashes:
    raise ValueError('Evidence input set must not be empty')
  return digest(json_bytes(hashes))


def tree_files(root: Path) -> dict[str, Path]:
  """Collect a source/package tree without caches, build metadata or secrets."""
  if not root.is_dir() or root.is_symlink():
    raise ValueError('Evidence source directory is missing or a symlink')
  files: dict[str, Path] = {}
  for path in root.rglob('*'):
    parts = path.relative_to(root).parts
    if any(p in SKIP_DIRS or p.endswith(('.egg-info', '.dist-info')) for p in parts):
      continue
    if any(p == '.env' or p.startswith('.env.') for p in parts):
      continue
    if path.suffix in {'.pyc', '.pyo'}:
      continue
    if path.is_symlink():
      raise ValueError('Evidence source trees must not contain symlinks')
    if path.is_file():
      files[path.relative_to(root).as_posix()] = path
  return files


def package_roots(root: Path, venue: str) -> dict[str, Path]:
  """Resolve only explicitly selected SDK packages, never arbitrary paths."""
  if not re.fullmatch(r'[a-z][a-z0-9_-]*', venue):
    raise ValueError('Invalid evidence venue')
  return {
    'tribulnation-sdk': root / 'packages/sdk/pkg',
    'sdk-dev': root / 'packages/sdk-dev/pkg',
    f'tribulnation-{venue}': root / f'packages/impl/{venue}/pkg',
  }


def candidate_files(root: Path, venue: str) -> dict[str, Path]:
  """Select candidate sources, tests and non-secret behavior configuration."""
  files: dict[str, Path] = {}
  for package in package_roots(root, venue).values():
    for directory in (package / 'src', package.parent / 'test'):
      for path in tree_files(directory).values():
        files[path.relative_to(root).as_posix()] = path
    project = package / 'pyproject.toml'
    files[project.relative_to(root).as_posix()] = project
  for name in (
    'registry.toml',
    'pytest.ini',
    'pyrightconfig.json',
    '.python-version',
    'requirements.txt',
    'conftest.py',
  ):
    path = root / name
    if path.exists():
      files[name] = path
  support = root / f'packages/impl/{venue}/impl.toml'
  files[support.relative_to(root).as_posix()] = support
  integration = root / f'packages/impl/{venue}/integration'
  if integration.is_dir():
    for path in tree_files(integration).values():
      files[path.relative_to(root).as_posix()] = path
  return files


def editable_root(dist: metadata.Distribution) -> Path | None:
  """Locate actual editable source from installed distribution metadata."""
  raw = dist.read_text('direct_url.json')
  if raw is None:
    return None
  info = DirectURL.model_validate_json(raw)
  if not info.dir_info.editable:
    return None
  url = urlparse(info.url)
  if url.scheme != 'file' or url.netloc not in ('', 'localhost'):
    raise ValueError('Editable evidence dependencies must use local file sources')
  package = Path(unquote(url.path)).resolve()
  if not (package / 'src').is_dir():
    raise ValueError('Editable dependency has no supported src-layout source tree')
  return package


def verify_imports(dist: metadata.Distribution, source: Path, files: dict[str, Path]):
  """Reject shadowed top-level imports instead of hashing unused installed code."""
  names = {
    name.split('/')[0].removesuffix('.py')
    for name in files
    if '/' in name or name.endswith('.py')
  }
  installed_files = {path.resolve() for path in files.values()}
  for name in sorted(names):
    if not name.isidentifier() or name.startswith('_'):
      continue
    spec = util.find_spec(name)
    if spec is None:
      raise ValueError(
        f'Installed dependency import is missing: {dist.metadata["Name"]}'
      )
    if spec.origin not in (None, 'namespace'):
      origin = Path(spec.origin).resolve()
      if not origin.is_relative_to(source.resolve()) or origin not in installed_files:
        raise ValueError(f'Dependency import is shadowed: {name}')


def dependency(dist: metadata.Distribution) -> Dependency:
  """Hash actual installed code; editable and wheel source layouts normalize alike."""
  editable = editable_root(dist)
  if editable is not None:
    source = editable / 'src'
    files = tree_files(source)
  else:
    source = Path(str(dist.locate_file(''))).resolve()
    files = {}
    installed = dist.files
    if not installed:
      raise ValueError('Installed dependency has no file inventory')
    for item in installed:
      name = item.as_posix()
      if (
        name.startswith('../')
        or any(
          p.endswith(('.dist-info', '.egg-info')) or p == '__pycache__'
          for p in item.parts
        )
        or item.suffix in {'.pyc', '.pyo'}
      ):
        continue
      files[name] = Path(str(dist.locate_file(item)))
  verify_imports(dist, source, files)
  identity: dict[str, object] = {
    'name': canonicalize_name(dist.metadata['Name']),
    'version': dist.version,
    'requires_python': dist.metadata['Requires-Python']
    if 'Requires-Python' in dist.metadata
    else None,
    'requires_dist': sorted(dist.requires or ()),
    'entry_points': sorted(
      (entry.group, entry.name, entry.value) for entry in dist.entry_points
    ),
  }
  return Dependency(
    version=dist.version,
    metadata_sha256=digest(json_bytes(identity)),
    # Metadata-only metapackages (e.g. griffe) have no importable files. Their
    # requirements and entry points are hashed above; dependencies are traversed.
    files_sha256=files_digest(files) if files else digest(json_bytes({})),
  )


def installed_dependencies(root: Path, venue: str) -> dict[str, Dependency]:
  """Follow active installed requirements, including transitively requested extras."""
  packages = package_roots(root, venue)
  queue = [Requirement(name) for name in packages]
  seen: dict[str, set[str]] = {}
  result: dict[str, Dependency] = {}
  while queue:
    requirement = queue.pop()
    name = canonicalize_name(requirement.name)
    extras = set(requirement.extras) | {''}
    previous = seen.get(name, set())
    dist = metadata.distribution(name)
    if requirement.specifier and not requirement.specifier.contains(dist.version):
      raise ValueError(f'Installed dependency violates requirement: {name}')
    if extras <= previous:
      continue
    seen[name] = previous | extras
    if name in packages:
      if editable_root(dist) != packages[name].resolve():
        raise ValueError(
          f'Candidate package is not installed from this checkout: {name}'
        )
      module = 'sdk_dev' if name == 'sdk-dev' else name.replace('-', '.')
      spec = util.find_spec(module)
      if (
        spec is None
        or spec.origin is None
        or not Path(spec.origin)
        .resolve()
        .is_relative_to((packages[name] / 'src').resolve())
      ):
        raise ValueError(f'Candidate package import is shadowed: {name}')
      declared = tomllib.loads((packages[name] / 'pyproject.toml').read_text())[
        'project'
      ]
      if declared['version'] != dist.version:
        raise ValueError(
          f'Candidate package version differs from installed metadata: {name}'
        )
      installed = {str(Requirement(raw)) for raw in dist.requires or ()}
      if (
        not {str(Requirement(raw)) for raw in declared.get('dependencies', ())}
        <= installed
      ):
        raise ValueError(
          f'Candidate package requirements differ from installed metadata: {name}'
        )
    if name not in result:
      result[name] = dependency(dist)
    for raw in dist.requires or ():
      child = Requirement(raw)
      if child.marker is None or any(
        child.marker.evaluate({'extra': extra}) for extra in extras
      ):
        queue.append(child)
  return result


def capture(root: Path, venue: str, catalogue: Path) -> Snapshot:
  """Fingerprint candidate and actual runtime inputs without reading credentials."""
  root = root.resolve()
  catalogue = catalogue.resolve()
  catalogue_files = {
    name: path for name, path in tree_files(catalogue).items() if path.suffix == '.json'
  }
  return Snapshot(
    venue=venue,
    python=f'{sys.version_info.major}.{sys.version_info.minor}',
    source_sha256=files_digest(candidate_files(root, venue)),
    catalogue_sha256=files_digest(catalogue_files),
    dependencies=installed_dependencies(root, venue),
  )


def check_public_payload(value: JsonValue):
  """Reject obvious private/raw payload keys; callers must supply sanitized checks."""
  if isinstance(value, dict):
    for key, child in value.items():
      if key.lower() in SENSITIVE_KEYS:
        raise ValueError('Evidence payload contains a forbidden private/raw field')
      check_public_payload(child)
  elif isinstance(value, list):
    for child in value:
      check_public_payload(child)


def check_times(started: datetime, finished: datetime, *, now: datetime):
  """Require an aware completed run no older than seven days and never future-dated."""
  if started.utcoffset() is None or finished.utcoffset() is None:
    raise ValueError('Evidence timestamps must be timezone-aware')
  if started > finished or finished > now:
    raise ValueError('Evidence timestamps are inconsistent or in the future')
  if now - started > MAX_AGE:
    raise ValueError('Evidence is older than seven days')


def dependency_pins(snapshot: Snapshot) -> str:
  """Render safe external distribution pins for reproducing the checked runtime."""
  own = {'sdk-dev', 'tribulnation-sdk', f'tribulnation-{snapshot.venue}'}
  lines: list[str] = []
  for name, dep in sorted(snapshot.dependencies.items()):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
      raise ValueError('Invalid dependency name in evidence')
    Version(dep.version)
    if name not in own:
      lines.append(f'{name}=={dep.version}')
  return '\n'.join(lines) + '\n'


def write_report(
  output: Path,
  *,
  before: Snapshot,
  after: Snapshot,
  payload: dict[str, object],
  started: datetime,
  finished: datetime,
):
  """Write a new report directory; interrupted writes remain unverifiable."""
  if before != after:
    raise ValueError('Evidence inputs changed during the run')
  check_times(started, finished, now=datetime.now(timezone.utc))
  results = Results.model_validate({'payload': payload})
  if results.payload.get('venue') != before.venue:
    raise ValueError('Evidence payload venue does not match its snapshot')
  check_public_payload(results.payload)
  body = json_bytes(results.model_dump(mode='json'))
  summary = (
    f'# Local SDK evidence: {before.venue}\n\n'
    f'Run completed: {finished.isoformat()}\n\n'
    'This records a trusted local run, not cryptographic proof. '
    'Release policy must separately validate required check coverage and statuses.\n'
  )
  if results.payload.get('private_account_venue') == 'deribit_testnet':
    summary += (
      '\nQualification: Wallet/Earn public metadata on mainnet; private Report '
      'functionality on testnet only. Mainnet private-account behavior is unverified.\n'
    )
  summary = summary.encode()
  manifest = Manifest(
    before=before,
    after=after,
    started=started,
    finished=finished,
    results_sha256=digest(body),
    summary_sha256=digest(summary),
  )
  pins = dependency_pins(before)
  output.mkdir(parents=True, exist_ok=False)
  (output / 'results.json').write_bytes(body)
  (output / 'summary.md').write_bytes(summary)
  (output / 'dependency-pins.txt').write_text(pins)
  (output / 'manifest.json').write_bytes(json_bytes(manifest.model_dump(mode='json')))


def verify_report(root: Path, report: Path, catalogue: Path) -> dict[str, object]:
  """Validate report integrity, age and current inputs without live venue calls."""
  paths = {
    name: report / name
    for name in (
      'manifest.json',
      'results.json',
      'summary.md',
      'dependency-pins.txt',
    )
  }
  if report.is_symlink() or any(
    p.is_symlink() or not p.is_file() for p in paths.values()
  ):
    raise ValueError('Evidence report is missing files or contains symlinks')
  manifest = Manifest.model_validate_json(paths['manifest.json'].read_bytes())
  check_times(manifest.started, manifest.finished, now=datetime.now(timezone.utc))
  body = paths['results.json'].read_bytes()
  summary = paths['summary.md'].read_bytes()
  if (
    digest(body) != manifest.results_sha256
    or digest(summary) != manifest.summary_sha256
  ):
    raise ValueError('Evidence report contents were modified')
  if manifest.before != manifest.after:
    raise ValueError('Evidence inputs changed during the run')
  if paths['dependency-pins.txt'].read_text() != dependency_pins(manifest.before):
    raise ValueError('Evidence dependency pins were modified')
  current = capture(root, manifest.before.venue, catalogue)
  if current != manifest.before:
    changed = [
      name
      for name in ('python', 'source_sha256', 'catalogue_sha256')
      if getattr(current, name) != getattr(manifest.before, name)
    ]
    changed += [
      f'dependency:{name}'
      for name in sorted(
        current.dependencies.keys() | manifest.before.dependencies.keys()
      )
      if current.dependencies.get(name) != manifest.before.dependencies.get(name)
    ]
    raise ValueError('Evidence does not match current inputs: ' + ', '.join(changed))
  results = Results.model_validate_json(body)
  if results.payload.get('venue') != manifest.before.venue:
    raise ValueError('Evidence payload venue does not match its snapshot')
  check_public_payload(results.payload)
  return dict(results.payload)
