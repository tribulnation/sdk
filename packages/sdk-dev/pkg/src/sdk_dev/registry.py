"""Reads the repo-root `registry.toml` — the hand-authored venue list for the /sdk site's
venue picker and logo wall. Mirrors typed-dev's own registry.toml/registry.json split
(ADR 0016): a single trusted-outright TOML file in, one JSON object per venue out, array
order preserved as display order.
"""

import tomllib

import pydantic


class RegistryVenue(pydantic.BaseModel):
  """One `[[venues]]` entry in `registry.toml`."""

  model_config = pydantic.ConfigDict(extra='forbid')

  slug: str
  name: str | None = None
  tier: str
  repo: str | None = None
  path: str | None = None
  pypi: str | None = None
  icon: str | None = None


class RegistryFile(pydantic.BaseModel):
  """The full shape of `registry.toml` — a bare `venues` array."""

  model_config = pydantic.ConfigDict(extra='forbid')

  venues: list[RegistryVenue] = []


def load_registry(path: str) -> dict[str, dict]:
  """
  Parse `registry.toml` into a `{slug: entry}` dict, JSON-serializable as-is.

  Args:
    path: Path to registry.toml.

  Returns:
    Venue entries keyed by slug, in file order (dict insertion order survives both
    `json.dumps` and JS's own `JSON.parse`/`Object.entries`, so no explicit order field
    is needed downstream).

  Raises:
    pydantic.ValidationError: `registry.toml` doesn't match `RegistryFile`'s shape.
  """
  with open(path, 'rb') as f:
    raw = tomllib.load(f)
  data = RegistryFile.model_validate(raw)
  entries: dict[str, dict] = {}
  for venue in data.venues:
    entry = venue.model_dump(exclude={'slug'}, exclude_none=True)
    entry.setdefault('name', venue.slug.capitalize())
    entries[venue.slug] = entry
  return entries
