"""Emit each economic fill once when two sources race (`trades_source='fastest'`)."""

from typing_extensions import Literal
from dataclasses import dataclass, field

from .node_fills import FillKey

Source = Literal['node', 'indexer']

DEDUP_WINDOW = 1000
"""Blocks a fill key is remembered for (about 15 to 20 minutes of dYdX blocks)."""


@dataclass
class FillDedup:
  """Admit the first copy of each fill, from whichever source delivers it first.

  Keys are counted as multisets: two identical fills in one block (same order, same
  size) are two fills, so the `n`-th copy from a source is admitted only if neither
  source delivered `n` copies before. Keys are forgotten `window` blocks behind the
  highest height seen; a fill older than that is assumed delivered already and dropped,
  so a source lagging the other by more than the window cannot replay its backlog.
  """

  window: int = DEDUP_WINDOW
  max_height: int = 0
  seen: dict[int, dict[FillKey, dict[Source, int]]] = field(
    default_factory=dict[int, dict[FillKey, dict[Source, int]]]
  )
  """Copies per source of each key, by height."""

  def admit(self, source: Source, key: FillKey | None) -> bool:
    """Whether to emit this copy of a fill.

    Args:
      source: The source that delivered it.
      key: Its key; `None` (no height to key it by) is always admitted.
    """
    if key is None:
      return True
    if key.height <= self.max_height - self.window:
      return False
    if key.height > self.max_height:
      self.max_height = key.height
      horizon = self.max_height - self.window
      for height in [h for h in self.seen if h <= horizon]:
        del self.seen[height]
    counts = self.seen.setdefault(key.height, {}).setdefault(key, {})
    emitted = max(counts.values(), default=0)
    counts[source] = counts.get(source, 0) + 1
    return counts[source] > emitted
