"""Share venue qualification boundaries between fingerprints and release impact."""

import ast
from pathlib import Path
import subprocess
import tomllib

from packaging.version import Version
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

GATEWAY_SOURCE = 'packages/sdk/pkg/src/tribulnation/sdk/gateway/'
GATEWAY_TEST = 'packages/sdk/test/gateway/'
SHARED = {
  'registry.toml',
  'pytest.ini',
  'pyrightconfig.json',
  '.python-version',
  'requirements.txt',
  'conftest.py',
}

OFFLINE_SOURCES = {'sdk_dev/evidence.py', 'sdk_dev/release_scope.py'}
"""Report integrity and impact verification do not execute venue observations."""
OFFLINE_COMMANDS = {
  'verify_one',
  'verify',
  'required_venues',
  'required_scopes',
  'release_scope',
  'release',
}
"""Only these commands in the mixed results module are offline-only."""


def sdk_requirement(raw: str) -> bool:
  """Exclude command-provider wiring from venue runtime dependencies."""
  requirement = Requirement(raw)
  return (
    canonicalize_name(requirement.name) != 'tribulnation-cli'
    and str(requirement.marker) != 'extra == "gateway"'
  )


def relevant_path(name: str, venue: str) -> bool:
  """Include shared SDK and qualification inputs plus the selected adapter."""
  if name.startswith((GATEWAY_SOURCE, GATEWAY_TEST)):
    return False
  if name.startswith('packages/sdk-dev/test/') or name in {
    f'packages/sdk-dev/pkg/src/{path}' for path in OFFLINE_SOURCES
  }:
    return False
  roots = ('packages/sdk', 'packages/sdk-dev', f'packages/impl/{venue}')
  return (
    name in SHARED
    or any(
      name == f'{root}/pkg/pyproject.toml'
      or name.startswith((f'{root}/pkg/src/', f'{root}/test/', f'{root}/integration/'))
      for root in roots
    )
    or name == f'packages/impl/{venue}/impl.toml'
  )


def project_inputs(data: bytes, *, sdk: bool) -> dict[str, object]:
  """Keep behavior/build metadata while excluding release labels and SDK gateway wiring."""
  document = tomllib.loads(data.decode())
  project = document.get('project', {})
  for key in (
    'version',
    'description',
    'authors',
    'maintainers',
    'readme',
    'license',
    'license-files',
    'classifiers',
    'urls',
    'keywords',
  ):
    project.pop(key, None)
  if sdk:
    dependencies = [
      raw for raw in project.get('dependencies', []) if sdk_requirement(raw)
    ]
    if dependencies:
      project['dependencies'] = dependencies
    else:
      project.pop('dependencies', None)
    project.get('optional-dependencies', {}).pop('gateway', None)
    if not project.get('optional-dependencies'):
      project.pop('optional-dependencies', None)
    providers = project.get('entry-points', {}).get('tribulnation.commands', {})
    providers.pop('gateway', None)
    if not providers:
      project.get('entry-points', {}).pop('tribulnation.commands', None)
    if not project.get('entry-points'):
      project.pop('entry-points', None)
  return document


def normalized_input(name: str, data: bytes) -> bytes:
  """Normalize only documented non-qualification packaging changes."""
  import json

  if name == 'packages/sdk-dev/pkg/src/sdk_dev/cli/results.py':
    module = ast.parse(data)
    module.body = [
      node
      for node in module.body
      if not (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in OFFLINE_COMMANDS
        or isinstance(node, ast.ImportFrom)
        and node.module == 'sdk_dev.release_scope'
      )
    ]
    return ast.dump(module, include_attributes=False).encode()
  if name.endswith('/pkg/pyproject.toml'):
    return json.dumps(
      project_inputs(data, sdk=name == 'packages/sdk/pkg/pyproject.toml'),
      sort_keys=True,
    ).encode()
  if name == 'requirements.txt':
    return data.replace(b'-e packages/sdk/pkg[gateway]', b'-e packages/sdk/pkg')
  return data


def git(root: Path, *args: str) -> bytes:
  """Read release history without invoking a shell or fetching moving references."""
  result = subprocess.run(
    ['git', '-C', str(root), *args], capture_output=True, check=False
  )
  if result.returncode:
    raise ValueError('Release history is unavailable; fetch complete history and tags')
  return result.stdout


def previous_release(root: Path, package: str) -> str | None:
  """Choose the highest prior version tag reachable from the exact candidate."""
  if git(root, 'rev-parse', '--is-shallow-repository').strip() != b'false':
    raise ValueError('Release impact requires complete history and tags')
  folder = 'packages/sdk' if package == 'sdk' else f'packages/impl/{package}'
  version = Version(
    tomllib.loads((root / folder / 'pkg/pyproject.toml').read_text())['project'][
      'version'
    ]
  )
  tags = (
    git(root, 'tag', '--merged', 'HEAD', '--list', f'{package}-v*')
    .decode()
    .splitlines()
  )
  previous = [(Version(tag.removeprefix(f'{package}-v')), tag) for tag in tags]
  return max((item for item in previous if item[0] < version), default=(None, None))[1]


def affected_venues(root: Path, package: str, venues: list[str]) -> list[str]:
  """Compare the entire release against its published baseline; first releases qualify all."""
  dirty = (
    git(root, 'diff', '--no-renames', '--name-only', '-z', 'HEAD').decode().split('\0')
  )
  dirty += (
    git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')
  )
  if any(relevant_path(name, venue) for name in dirty for venue in venues):
    raise ValueError('Release impact requires a clean checkout of qualification inputs')
  baseline = previous_release(root, package)
  if baseline is None:
    return venues
  affected: list[str] = []
  for venue in venues:
    qualified = baseline
    if package == 'sdk':
      # An independently published adapter has already qualified shared inputs
      # through its release commit. Never use an unmerged or future-version tag.
      project = root / f'packages/impl/{venue}/pkg/pyproject.toml'
      if project.is_file():
        version = Version(tomllib.loads(project.read_text())['project']['version'])
        tags = (
          git(root, 'tag', '--merged', 'HEAD', '--list', f'{venue}-v*')
          .decode()
          .splitlines()
        )
        prior = [(Version(tag.removeprefix(f'{venue}-v')), tag) for tag in tags]
        released = max(
          (item for item in prior if item[0] <= version), default=(None, None)
        )[1]
        if released is not None:
          ancestor = git(root, 'merge-base', baseline, released).strip()
          if ancestor == git(root, 'rev-parse', f'{baseline}^{{commit}}').strip():
            qualified = released
    if venue_changed(root, venue, qualified):
      affected.append(venue)
  return sorted(affected)


def venue_changed(root: Path, venue: str, baseline: str) -> bool:
  """Compare every relevant input since this venue's latest qualification release."""
  changed = (
    git(root, 'diff', '--no-renames', '--name-only', '-z', baseline, 'HEAD')
    .decode()
    .split('\0')
  )
  for name in filter(None, changed):
    if not relevant_path(name, venue):
      continue
    contents: list[bytes | None] = []
    for ref in (baseline, 'HEAD'):
      exists = git(root, 'ls-tree', ref, '--', name).strip()
      contents.append(
        normalized_input(name, git(root, 'show', f'{ref}:{name}')) if exists else None
      )
    if contents[0] != contents[1]:
      return True
  return False


def declared_venues(root: Path, package: str) -> list[str]:
  """Select supported implementations without importing venue drivers."""
  venues = sorted(
    path.parent.name
    for path in (root / 'packages/impl').glob('*/impl.toml')
    if any(
      item.get('support', 'none') != 'none'
      for item in tomllib.loads(path.read_text()).get('support', {}).values()
    )
  )
  if package == 'sdk' and venues:
    return venues
  if package in venues:
    return [package]
  raise ValueError('No consistency release-evidence policy for this package yet')


if __name__ == '__main__':
  import os
  import sys

  root = Path.cwd()
  package = sys.argv[1]
  try:
    venues = affected_venues(root, package, declared_venues(root, package))
  except (ValueError, OSError) as exception:
    sys.exit(f'Release blocked: {exception}')
  print('Required venue evidence: ' + (', '.join(venues) or 'none'))
  with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write('venues=' + ','.join(venues) + '\n')
