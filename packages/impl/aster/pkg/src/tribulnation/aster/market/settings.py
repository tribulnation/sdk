"""Aster order settings, under `settings['aster']`."""

from typing_extensions import Literal, TypedDict


class Settings(TypedDict, total=False):
  """Aster order settings, under `settings['aster']`."""

  time_in_force: Literal['IOC']
  """Send a `LIMIT` order immediate-or-cancel instead of GTC: it fills what it can at
  the limit price or better and expires the rest. `POST_ONLY` and `MARKET` orders
  raise `ValueError` when it is set."""
