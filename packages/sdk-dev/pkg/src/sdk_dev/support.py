"""Aggregates every `packages/impl/*/impl.toml` into a per-surface support matrix —
which venues offer a given surface (`supportedVenues`) and which of those have a real
credential-free `DEFAULT_ACCOUNTS` entry for it (`defaultVenues`). This is what the /sdk
wizard's venue picker and sdk.toml generation are driven by, so a venue only ever shows up
there once its own package's impl.toml says it's ready — never derived from router code
alone (a venue can be wired into an *SDK's router ahead of being ready to announce; see
any impl.toml's own comments for real examples of that gate in use).
"""

from pathlib import Path
import tomllib

import pydantic
from typing_extensions import Literal


class ImplSurfaceSupport(pydantic.BaseModel):
  """One `[support.<surface>]` table in a package's `impl.toml`."""

  model_config = pydantic.ConfigDict(extra='forbid')

  support: Literal['full', 'partial']
  auth: bool
  methods: list[str] | None = None


class ImplFile(pydantic.BaseModel):
  """The full shape of a package's `impl.toml` — a bare `support` table of tables."""

  model_config = pydantic.ConfigDict(extra='forbid')

  support: dict[str, ImplSurfaceSupport] = {}


def load_impl_files(impl_dir: Path) -> dict[str, ImplFile]:
  """
  Parse and validate every `packages/impl/*/impl.toml` under `impl_dir`.

  Args:
    impl_dir: Path to the sdk repo's `packages/impl` directory.

  Returns:
    Validated `ImplFile`s keyed by package slug (its directory name), one per package
    that has an `impl.toml` at all.

  Raises:
    pydantic.ValidationError: some impl.toml doesn't match `ImplFile`'s shape.
  """
  files: dict[str, ImplFile] = {}
  for pkg_dir in sorted(impl_dir.iterdir()):
    impl_toml = pkg_dir / 'impl.toml'
    if not impl_toml.is_file():
      continue
    with open(impl_toml, 'rb') as f:
      raw = tomllib.load(f)
    files[pkg_dir.name] = ImplFile.model_validate(raw)
  return files


def method_universe(
  impl_files: dict[str, ImplFile], surface: str, method: str
) -> list[str]:
  """
  Every venue genuinely eligible to serve one method of one surface, per every
  `impl.toml`'s `[support.<surface>]` table.

  Args:
    impl_files: `load_impl_files()`'s output.
    surface: A surface name — by convention, a `docs/contract/<surface>.yml`'s own
      filename stem, never hardcoded by any caller.
    method: The method name (a `docs/contract/<surface>.yml`'s `methods.<method>` key).

  Returns:
    Slugs (impl_files' own iteration order — alphabetical) of every venue whose
    impl.toml declares this surface with `support: full`, or `support: partial` with
    this method in its `methods` list. This is the outer bound on which venues a
    method's `.yml` template can be rendered for — see `sdk_dev.contract.render_method`.
  """
  eligible = []
  for slug, data in impl_files.items():
    entry = data.support.get(surface)
    if entry is None:
      continue
    if entry.support == 'full' or (entry.methods and method in entry.methods):
      eligible.append(slug)
  return eligible


def load_support_matrix(impl_dir: Path) -> dict[str, dict[str, list[str]]]:
  """
  Build `{surface: {supportedVenues: [...], defaultVenues: [...]}}` from every
  `packages/impl/*/impl.toml` under `impl_dir`.

  Args:
    impl_dir: Path to the sdk repo's `packages/impl` directory.

  Returns:
    One entry per surface named in any impl.toml's `[support.<surface>]` table. Venue
    order here is just directory-listing order (alphabetical) — display order is a
    presentation concern resolved downstream, by filtering registry.toml's own
    deliberately-ordered venue list against this data's membership, not by iterating
    this list directly.

  Raises:
    pydantic.ValidationError: some impl.toml doesn't match `ImplFile`'s shape.
  """
  matrix: dict[str, dict[str, list[str]]] = {}
  for slug, data in load_impl_files(impl_dir).items():
    for surface, entry in data.support.items():
      bucket = matrix.setdefault(surface, {'supportedVenues': [], 'defaultVenues': []})
      bucket['supportedVenues'].append(slug)
      if not entry.auth:
        bucket['defaultVenues'].append(slug)
  return matrix
