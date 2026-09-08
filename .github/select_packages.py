"""Select buildable packages affected by a change, excluding PoC-only directories."""

from pathlib import Path
import json
import sys

SHARED = {
  'requirements.txt',
  'pyrightconfig.json',
  'pytest.ini',
  'ruff.toml',
  '.agents/tools/python/ruff.toml',
  '.github/workflows/check.yml',
  '.github/select_packages.py',
}
"""Changes that require checking every buildable package."""


def select_packages(root: Path, changed: list[str]) -> list[str]:
  """Return matrix names only for packages with an actual build manifest."""
  available = {
    path.parent.parent.name
    for path in (root / 'packages' / 'impl').glob('*/pkg/pyproject.toml')
    if path.is_file()
  }
  available.update(
    name
    for name in ('sdk', 'sdk-dev')
    if (root / 'packages' / name / 'pkg' / 'pyproject.toml').is_file()
  )
  selected: set[str] = set()
  for name in changed:
    if name in SHARED or name.startswith('packages/sdk/'):
      return sorted(available)
    parts = Path(name).parts
    if len(parts) >= 3 and parts[:2] == ('packages', 'impl'):
      selected.add(parts[2])
    elif len(parts) >= 2 and parts[:2] == ('packages', 'sdk-dev'):
      selected.add('sdk-dev')
  return sorted(selected & available)


if __name__ == '__main__':
  print(json.dumps(select_packages(Path.cwd(), [line.strip() for line in sys.stdin])))
