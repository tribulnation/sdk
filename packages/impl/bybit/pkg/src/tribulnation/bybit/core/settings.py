"""Client-level knobs shared by every Bybit surface."""

from typing_extensions import TypedDict


class Settings(TypedDict, total=False):
  """Per-client Bybit settings."""

  validate: bool
  """Validate responses against the client's declared schemas. Defaults to `True`."""
