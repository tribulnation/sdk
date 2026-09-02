"""Validates `docs/docs.toml`, the sidebar-order file the docs site reads: one `[nav...]`
table per directory, each with an `order` list of sibling files and directories. The
site tolerates nothing missing, so a stale entry is caught here before a sync.
"""

from pathlib import Path
import tomllib

import pydantic

NAV_FILENAME = 'docs.toml'


class NavTable(pydantic.BaseModel):
  """One directory's entry: which siblings come first, in what order."""

  model_config = pydantic.ConfigDict(extra='forbid')

  title: str | None = None
  """Sidebar label for this directory; defaults to its name, title-cased."""
  order: list[str] = []
  """Sibling files (`foo.md`) and directories (`foo`) in display order. `index.md` is
  implicit and always first."""


def check_nav(docs_dir: Path) -> int:
  """
  Validate `docs_dir/docs.toml` against the directory tree.

  Args:
    docs_dir: The sdk repo's `docs/` directory.

  Returns:
    The number of directory tables validated.

  Raises:
    ValueError: a table names a directory or entry that doesn't exist, an entry is
      listed twice, or a table has a key other than `title`/`order`.
  """
  path = docs_dir / NAV_FILENAME
  if not path.is_file():
    return 0
  with open(path, 'rb') as f:
    raw = tomllib.load(f)
  nav = raw.get('nav')
  if not isinstance(nav, dict) or set(raw) != {'nav'}:
    raise ValueError(f'{path}: expected a single top-level [nav] table')
  return _check_table(path, nav, docs_dir, 'nav')


def _check_table(path: Path, raw: dict, directory: Path, key: str) -> int:
  """Validate one directory's table and recurse into its sub-directory tables."""
  own = {k: v for k, v in raw.items() if not isinstance(v, dict)}
  try:
    table = NavTable.model_validate(own)
  except pydantic.ValidationError as e:
    raise ValueError(f'{path}: [{key}]: {e}') from e
  if len(set(table.order)) != len(table.order):
    raise ValueError(f'{path}: [{key}]: duplicate entry in `order`')
  for entry in table.order:
    if entry == 'index.md':
      raise ValueError(f'{path}: [{key}]: `index.md` is implicit, leave it out')
    target = directory / entry
    if not (target.is_file() if entry.endswith('.md') else target.is_dir()):
      raise ValueError(f'{path}: [{key}]: {entry!r} does not exist in {directory}')
  count = 1
  for name, sub in raw.items():
    if isinstance(sub, dict):
      if not (directory / name).is_dir():
        raise ValueError(f'{path}: [{key}.{name}]: no such directory in {directory}')
      count += _check_table(path, sub, directory / name, f'{key}.{name}')
  return count
