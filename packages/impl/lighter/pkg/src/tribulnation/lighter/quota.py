"""Log the volume quota Lighter reports on each order transaction, throttled.

A Premium account spends volume quota on creates, modifies and cancel-alls; every
`sendTx` and `sendTxBatch` reply carries what remains (`volume_quota_remaining`),
except the free transaction Lighter allows every 15 seconds.

References:
  - [Lighter volume quota](https://docs.lighter.xyz/developers/reference/volume-quota.md)
"""

from dataclasses import dataclass
import logging
import time

from typing_extensions import Callable, Mapping

log = logging.getLogger(__name__)

LOG_INTERVAL = 600.0
"""Seconds between INFO logs of an unchanged-enough quota."""
LOG_STEP = 500
"""A quota this far from the last logged one is logged at once."""
LOW_THRESHOLD = 2_000
"""Below this, the quota logs at WARNING instead of INFO."""
LOW_INTERVAL = 60.0
"""Seconds between WARNING logs of a low quota."""


@dataclass(kw_only=True)
class VolumeQuota:
  """Track one account's remaining volume quota and log it, throttled.

  At INFO: the first quota seen, then whenever `interval` seconds passed or it moved
  by `step` or more since the last log. At WARNING, instead: a quota below
  `threshold`, as soon as it drops below, then at most once per `low_interval` seconds.
  """

  account: str = 'lighter'
  """Account the quota belongs to, named in each log."""
  interval: float = LOG_INTERVAL
  step: int = LOG_STEP
  threshold: int = LOW_THRESHOLD
  low_interval: float = LOW_INTERVAL
  clock: Callable[[], float] = time.monotonic
  """Monotonic seconds, for the throttles."""
  remaining: int | None = None
  """The latest quota reported."""
  logged: int | None = None
  """The quota last logged."""
  logged_at: float | None = None
  """When the quota was last logged, on `clock`."""

  def record(self, response: Mapping[str, object]):
    """Note the quota of a `sendTx`-shaped reply, logging it if due."""
    remaining = response.get('volume_quota_remaining')
    if isinstance(remaining, int):
      self.update(remaining)

  def update(self, remaining: int):
    """Note `remaining`, logging it if due."""
    self.remaining = remaining
    now = self.clock()
    if remaining < self.threshold:
      if self.due(now, self.low_interval) or not self.was_low():
        log.warning(
          'Lighter volume quota remaining: %d (%s, below %d)',
          remaining,
          self.account,
          self.threshold,
        )
        self.mark(remaining, now)
    elif self.due(now, self.interval) or self.moved(remaining):
      log.info('Lighter volume quota remaining: %d (%s)', remaining, self.account)
      self.mark(remaining, now)

  def due(self, now: float, interval: float) -> bool:
    """Whether nothing was logged yet, or `interval` seconds passed since."""
    return self.logged_at is None or now - self.logged_at >= interval

  def was_low(self) -> bool:
    """Whether the quota last logged was below `threshold`."""
    return self.logged is not None and self.logged < self.threshold

  def moved(self, remaining: int) -> bool:
    """Whether `remaining` is `step` or more from the quota last logged."""
    return self.logged is not None and abs(remaining - self.logged) >= self.step

  def mark(self, remaining: int, now: float):
    """Remember what was logged, and when."""
    self.logged = remaining
    self.logged_at = now
