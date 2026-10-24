"""Emit each economic fill once when sources race (`trades_source='fastest'`)."""

from typing_extensions import Callable, Iterator, Literal, TypedDict
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import asyncio
import logging
import statistics

from .node_fills import FillKey

log = logging.getLogger(__name__)

Source = Literal['node', 'indexer', 'socket']

DEDUP_WINDOW = 1000
"""Blocks a fill key is remembered for (about 15 to 20 minutes of dYdX blocks)."""
RACE_SAMPLES = 1000
"""Leads kept per pair of sources, newest first out."""
RACE_LOG_INTERVAL = 600.0
"""Seconds between logs of a client's race statistics."""


class Lead(TypedDict):
  """How often and by how much one source beat another to the same fill."""

  first: Source
  second: Source
  fills: int
  """Fills both delivered, `first` before `second`, among the last `RACE_SAMPLES`."""
  p50_ms: float
  p90_ms: float


class RaceStats(TypedDict):
  """Which source delivered fills first, and by how much."""

  wins: dict[Source, int]
  """Fills each source delivered first, since the client opened."""
  leads: list[Lead]


@dataclass
class FillRace:
  """Which source delivers each fill first, and by how many milliseconds.

  One per client, shared by its `'fastest'` streams. A lead is recorded when a later
  source delivers a fill another delivered first. Streams of the same market see the
  same copies, so only the first of them racing a market records it (`racing`), and the
  statistics are logged every `RACE_LOG_INTERVAL` seconds while any stream races.
  """

  wins: dict[Source, int] = field(default_factory=dict[Source, int])
  """Fills each source delivered first."""
  leads: dict[tuple[Source, Source], deque[float]] = field(
    default_factory=dict[tuple[Source, Source], deque[float]]
  )
  """Leads in ms by `(first, second)`."""

  racers: dict[int, list[object]] = field(default_factory=dict[int, list[object]])
  """The streams racing each CLOB pair, oldest first; the oldest records."""
  reporter: 'asyncio.Task[None] | None' = None
  """Logs the statistics while any stream races."""

  @contextmanager
  def racing(self, clob_pair_id: int) -> Iterator[Callable[[], bool]]:
    """Register a stream racing a CLOB pair, for as long as the context lasts.

    Yields whether the stream records the race now: the market's oldest stream does,
    and the next takes over when it leaves. The first stream to race starts the
    statistics log, and the last to leave stops it. Must be entered in a running loop.
    """
    token = object()
    racers = self.racers.setdefault(clob_pair_id, [])
    racers.append(token)
    if self.reporter is None:
      self.reporter = asyncio.create_task(self.report())
    try:
      yield lambda: racers[0] is token
    finally:
      racers.remove(token)
      if not racers:
        del self.racers[clob_pair_id]
      if not self.racers and self.reporter is not None:
        self.reporter.cancel()
        self.reporter = None

  async def report(self):
    """Log the statistics now and then."""
    while True:
      await asyncio.sleep(RACE_LOG_INTERVAL)
      log.info('dYdX fill race: %s', self.stats())

  def won(self, source: Source):
    """`source` delivered a fill first."""
    self.wins[source] = self.wins.get(source, 0) + 1

  def lead(self, *, first: Source, second: Source, ms: float):
    """`second` delivered a fill `ms` after `first`."""
    self.leads.setdefault((first, second), deque(maxlen=RACE_SAMPLES)).append(ms)

  def summary(self) -> list[Lead]:
    """Per pair of sources, how often and by how much the first was ahead."""
    out: list[Lead] = []
    for (first, second), samples in sorted(self.leads.items()):
      xs = sorted(samples)
      out.append(
        {
          'first': first,
          'second': second,
          'fills': len(xs),
          'p50_ms': statistics.median(xs),
          'p90_ms': xs[min(len(xs) - 1, int(len(xs) * 0.9))],
        }
      )
    return out

  def stats(self) -> RaceStats:
    """Wins per source and leads per pair of sources."""
    return {'wins': dict(self.wins), 'leads': self.summary()}


@dataclass
class FillDedup:
  """Admit the first copy of each fill, from whichever source delivers it first.

  Keys are counted as multisets: two identical fills in one block (same order, same
  size) are two fills, so the `n`-th copy from a source is admitted only if no source
  delivered `n` copies before. Keys are forgotten `window` blocks behind the highest
  height seen; a fill older than that is assumed delivered already and dropped, so a
  source lagging another by more than the window cannot replay its backlog.
  """

  window: int = DEDUP_WINDOW
  race: FillRace = field(default_factory=FillRace)
  recording: Callable[[], bool] = lambda: True
  """Whether to record and log the race now (`FillRace.racing`)."""
  max_height: int = 0
  seen: dict[int, dict[FillKey, dict[Source, list[float]]]] = field(
    default_factory=dict[int, dict[FillKey, dict[Source, list[float]]]]
  )
  """Arrival times (monotonic seconds) of each key's copies, per source, by height."""

  def admit(
    self, source: Source, key: FillKey | None, *, at: float = 0.0, late: bool = False
  ) -> bool:
    """Whether to emit this copy of a fill.

    Args:
      source: The source that delivered it.
      key: Its key; `None` (no height to key it by) is always admitted.
      at: When it arrived, in seconds on a monotonic clock, for `race`.
      late: A copy backfilled after a reconnection: deduplicated, but not raced.
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
    copies = self.seen.setdefault(key.height, {}).setdefault(key, {})
    n = len(copies.get(source, []))
    earlier: list[tuple[float, Source]] = [
      (times[n], other)
      for other, times in copies.items()
      if other != source and len(times) > n
    ]
    copies.setdefault(source, []).append(at)
    recording = not late and self.recording()
    if earlier:
      if not recording:
        return False
      first_at, first = min(earlier)
      ms = (at - first_at) * 1000
      self.race.lead(first=first, second=source, ms=ms)
      log.info(
        'dYdX fill %s:%s:%s: %s first, %s +%.0f ms',
        key.height,
        key.subject,
        key.size,
        first,
        source,
        ms,
      )
      return False
    if recording:
      self.race.won(source)
    return True

  def retract(self, source: Source, key: FillKey):
    """Forget `source`'s latest copy of `key` (its proposal did not commit), so another
    source's copy of a real fill with that key can still be admitted."""
    times = self.seen.get(key.height, {}).get(key, {}).get(source)
    if times:
      times.pop()
