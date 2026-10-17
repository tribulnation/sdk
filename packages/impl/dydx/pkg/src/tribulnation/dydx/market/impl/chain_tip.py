"""The dYdX chain tip (latest block height and time), kept fresh in the background.

Order expiry used to cost one `get_latest_block` round trip per order. `ChainTip` polls
the node's CometBFT `/status` instead, a small response, and orders read the cached tip.

The tip is never extrapolated: a cached height is a lower bound on the true height, so an
expiry built from it is never later than one built from a live read. Its only risk is an
expiry that is too early, which `short_term_max_age` and `long_term_max_age` bound by
refusing a tip old enough for the order to have expired before it reaches the chain. A
tip older than that, or no tip at all, is read live with `get_latest_block`.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
import asyncio
import logging
import time

from typed_dydx.chain import Chain
from tribulnation.sdk.core import ValidationError

log = logging.getLogger(__name__)

MAX_AGE = 2.0
"""Seconds a cached tip may be old before orders read the tip live."""
POLL_INTERVAL = 0.2
"""Seconds between background `/status` reads."""
IDLE_AFTER = 30.0
"""Seconds without an order after which the background poll stops, until the next one."""
POLL_BACKOFF_MAX = 5.0
"""Cap of the background poll's backoff after failures, in seconds."""
MIN_BLOCK_INTERVAL = 0.4
"""A lower bound on the seconds between dYdX blocks (about 0.5-0.8 s on mainnet, 2026-10)."""


@dataclass(frozen=True)
class Tip:
  """The chain tip as one read saw it."""

  height: int
  """Latest committed block height."""
  time: datetime
  """That block's time."""
  observed: float
  """`time.monotonic()` when the read that saw it was sent."""

  def age(self) -> float:
    """Seconds since the read that saw this tip was sent."""
    return time.monotonic() - self.observed


def short_term_max_age(delta: int) -> float:
  """The oldest tip that leaves a short-term order expiring `delta` blocks past it alive.

  At most `ceil(age / MIN_BLOCK_INTERVAL)` blocks follow a tip of `age` seconds, so the
  order keeps at least one block of life while that is below `delta`. A `delta` of 1 or
  less always reads the tip live.
  """
  return (delta - 1) * MIN_BLOCK_INTERVAL


def long_term_max_age(delta: int) -> float:
  """The oldest tip that leaves a stateful order expiring `delta` seconds past it alive."""
  return float(delta - 1)


@dataclass
class ChainTip:
  """The latest block of one node, polled in the background once first read.

  The poll starts on the first `latest` call and stops when the owner exits
  (`stopping_poll`), or after
  `idle_after` seconds without a `latest` call (the next one restarts it). Its
  failures are logged and retried with backoff, never raised: the cached tip ages
  instead, and `latest` falls back to a live read. Heights never go backwards.
  """

  chain: Chain
  """The node to read: the account's full node when configured, else the public chain."""
  max_age: float = MAX_AGE
  """Seconds a cached tip may be old before `latest` reads it live."""
  poll_interval: float = POLL_INTERVAL
  """Seconds between background reads."""
  idle_after: float = IDLE_AFTER
  """Seconds without a `latest` call after which the poll stops."""
  last_read: float = 0.0
  """`time.monotonic()` of the last `latest` call."""
  tip: Tip | None = None
  """The newest tip seen, by the poll or a live read."""
  task: 'asyncio.Task[None] | None' = None
  """The background poll, once started."""

  def observe(self, tip: Tip):
    """Keep `tip` unless a higher block was already seen."""
    if self.tip is None or tip.height >= self.tip.height:
      self.tip = tip

  async def read_live(self) -> Tip:
    """Read the latest block with `get_latest_block` and cache it.

    Raises:
      ValidationError: When the response carries no header or block time.
    """
    observed = time.monotonic()
    latest = await self.chain.tendermint.get_latest_block()
    block = latest.block
    if block is None or block.header is None or block.header.time is None:
      raise ValidationError('Latest dYdX block response did not include a header')
    tip = Tip(height=block.header.height, time=block.header.time, observed=observed)
    self.observe(tip)
    return tip

  async def read_status(self) -> Tip | None:
    """Read the tip from the node's CometBFT `/status`, unless it is catching up."""
    observed = time.monotonic()
    sync = (await self.chain.comet.status())['sync_info']
    if not sync['catching_up']:
      return Tip(
        height=sync['latest_block_height'],
        time=sync['latest_block_time'],
        observed=observed,
      )

  async def poll(self):
    """Refresh the tip until idle, backing off while reads fail."""
    delay = self.poll_interval
    failing = False
    while time.monotonic() - self.last_read < self.idle_after:
      try:
        if (tip := await self.read_status()) is not None:
          self.observe(tip)
        delay = self.poll_interval
        failing = False
      except asyncio.CancelledError:
        raise
      except Exception as e:
        if not failing:
          log.warning('dYdX chain tip poll failed: %r; orders read the tip live', e)
        failing = True
        delay = min(max(delay, self.poll_interval) * 2, POLL_BACKOFF_MAX)
      await asyncio.sleep(delay)

  def start(self):
    """Start the background poll unless it is running."""
    if self.task is None or self.task.done():
      self.task = asyncio.create_task(self.poll(), name='dydx-chain-tip')

  async def latest(self, *, max_age: float) -> Tip:
    """The cached tip when it is at most `max_age` (and `self.max_age`) seconds old, else
    a live read.

    Args:
      max_age: The oldest tip the caller accepts, e.g. `short_term_max_age(delta)`.
    """
    self.last_read = time.monotonic()
    self.start()
    tip = self.tip
    if tip is not None and tip.age() <= min(max_age, self.max_age):
      return tip
    else:
      return await self.read_live()

  async def stop(self):
    """Cancel the background poll and wait for it to end."""
    task, self.task = self.task, None
    if task is not None:
      task.cancel()
      await asyncio.wait([task])


@asynccontextmanager
async def stopping_poll(tip: ChainTip):
  """Stop the tip's background poll at exit, if an order ever started it.

  Nothing is acquired on entry: the poll starts lazily inside the block.
  """
  try:
    yield tip
  finally:
    await tip.stop()
