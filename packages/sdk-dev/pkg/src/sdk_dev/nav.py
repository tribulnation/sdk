"""Reads `docs/docs.yml`, the sidebar order the docs site renders: a tree of entries
mirroring `docs/` itself, one entry per page or directory. `check_nav` validates it —
the site tolerates nothing missing, so a stale entry is caught here before a sync — and
`reading_order` flattens it into the page sequence behind the prev/next footers
(`sdk_dev.footers`).

The file only orders siblings; the structure is still the directory tree. `index.md`
comes first in its directory, then the entries listed here in order, then whatever
wasn't listed, alphabetically. So a new page needs an entry only to sit somewhere other
than the end.
"""

from pathlib import Path

import yaml

NAV_FILENAME = 'docs.yml'


def check_nav(docs_dir: Path) -> int:
  """
  Validate `docs_dir/docs.yml` against the directory tree.

  Args:
    docs_dir: The sdk repo's `docs/` directory.

  Returns:
    The number of pages it orders.

  Raises:
    ValueError: the file isn't a tree of entries, an entry names something that doesn't
      exist, an entry is listed twice, or `index.md` is listed explicitly.
  """
  return len(reading_order(docs_dir))


def reading_order(docs_dir: Path) -> list[Path]:
  """
  Every page under `docs_dir`, in the order the docs site lists them in its sidebar.

  Mirrors the landing's own tree walk (`scripts/render-docs.mjs`, `readTree` +
  `discoverPages`) — the site's page sequence is the one readers see, so it's the one
  the footers have to agree with. Directories holding no markdown at all (`contract/`,
  which is rendered rather than copied) drop out, exactly as they do there.

  Args:
    docs_dir: The sdk repo's `docs/` directory.

  Returns:
    Page paths relative to `docs_dir`.
  """
  path = docs_dir / NAV_FILENAME
  entries = []
  if path.is_file():
    entries = yaml.safe_load(path.read_text()) or []
    if not isinstance(entries, list):
      raise ValueError(f'{path}: expected a list of entries at the top level')
  return _walk(docs_dir, entries, Path('.'))


def _walk(directory: Path, entries: list, prefix: Path) -> list[Path]:
  """One directory's pages in sidebar order, each sub-directory's inlined where listed."""
  listed = _listed(directory, entries, prefix)
  contents = sorted(directory.iterdir(), key=lambda entry: entry.name)
  files = [e.name for e in contents if e.is_file() and e.suffix == '.md']
  names = list(listed)
  names += [name for name in files if name != 'index.md' and name not in listed]
  names += [e.name for e in contents if e.is_dir() and e.name not in listed]
  found = [prefix / 'index.md'] if 'index.md' in files else []
  for name in names:
    if name.endswith('.md'):
      found.append(prefix / name)
    else:
      found += _walk(directory / name, listed.get(name, []), prefix / name)
  return found


def _listed(directory: Path, entries: list, prefix: Path) -> dict[str, list]:
  """One directory's entries, validated: `{name: its own entries}`, in listed order."""
  where = f'{NAV_FILENAME}: {prefix}' if str(prefix) != '.' else NAV_FILENAME
  listed: dict[str, list] = {}
  for entry in entries:
    if isinstance(entry, str):
      name, own = entry, []
    elif isinstance(entry, dict) and len(entry) == 1:
      ((name, own),) = entry.items()
      own = own or []
      if not isinstance(name, str) or not isinstance(own, list):
        raise ValueError(
          f'{where}: {entry!r} should be `<directory>:` with its own list'
        )
    else:
      raise ValueError(
        f'{where}: expected a page name or `<directory>:` with its own list, got {entry!r}'
      )
    if name == 'index.md':
      raise ValueError(f'{where}: `index.md` is implicit, leave it out')
    if name in listed:
      raise ValueError(f'{where}: {name!r} is listed twice')
    target = directory / name
    if not (target.is_file() if name.endswith('.md') else target.is_dir()):
      raise ValueError(f'{where}: {name!r} does not exist')
    listed[name] = own
  return listed
