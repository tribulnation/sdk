"""Aster settings, under `settings['aster']`."""

from typing_extensions import Literal, TypedDict
from ..core import DepthSource


class Settings(TypedDict, total=False):
  """Aster settings, under `settings['aster']`."""

  time_in_force: Literal['IOC']
  """Send a `LIMIT` order immediate-or-cancel instead of GTC: it fills what it can at
  the limit price or better and expires the rest. `POST_ONLY` and `MARKET` orders
  raise `ValueError` when it is set."""
  depth_source: DepthSource
  """Which feed `depth_stream`/`depth` read. Defaults to `'depth'`.

  - `'depth'`: partial depth `@depth20`, 20 levels per side, pushed at most every
    250 ms on perpetuals and every 100 ms on spot (`@depth20@100ms`).
  - `'fast'`: partial depth `@depth5@100ms`, 5 levels per side at most every 100 ms on
    both exchanges. Faster than `'depth'` on perpetuals; on spot only shallower.
  - `'bbo'`: `@bookTicker`, the best bid and ask with sizes, pushed on every change.

  Every source can skip pushes while its levels are unchanged (observed on spot), so
  on a quiet book `Book.time` can lag the way a diff feed's does.

  The sources are different feeds and need not agree tick-for-tick. REST `depth` has
  no faster endpoint: `'fast'` and `'bbo'` read the smallest snapshot (5 levels),
  trimmed to 5 and 1 levels per side so its shape matches the stream's; `'depth'`
  keeps REST's deeper reach of up to 1000 levels.
  """
