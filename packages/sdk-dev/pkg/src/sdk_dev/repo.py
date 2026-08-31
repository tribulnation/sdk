"""Locates the sdk repo root and names the schema-governed source paths inside it, shared
by every `sdk-dev` command that reads them (`docs sync`, `docs check`, `support`).
"""

from pathlib import Path

CONTRACT_DIR = 'docs/contract'
IMPL_DIR = 'packages/impl'
REGISTRY_PATH = 'registry.toml'


class NotACheckout(Exception):
  """Raised when the current directory isn't inside an sdk repo checkout."""


def repo_root() -> Path:
  """
  Walk up from the current directory to the sdk repo root.

  Found by the presence of `docs/contract/` and `Justfile` together — unique to this
  repo's checkout, not wherever `sdk_dev` itself happens to be installed from.

  Raises:
    NotACheckout: no ancestor directory has both.
  """
  cwd = Path.cwd()
  for candidate in (cwd, *cwd.parents):
    if (candidate / 'docs' / 'contract').is_dir() and (
      candidate / 'Justfile'
    ).is_file():
      return candidate
  raise NotACheckout('Not inside an sdk repo checkout.')
