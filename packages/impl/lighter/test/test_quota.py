"""The remaining volume quota of order replies is logged, throttled."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing_extensions import Any, AsyncIterator, cast
import asyncio
import logging

import pytest
from typed_lighter import Lighter
from typed_lighter.schemas import SendTxResponse

from tribulnation.lighter.batching import OrderTx, TxBatcher
from tribulnation.lighter.quota import VolumeQuota

LOGGER = 'tribulnation.lighter'


@dataclass
class Clock:
  """A monotonic clock the test moves by hand."""

  now: float = 0.0

  def __call__(self) -> float:
    """The current fixture time."""
    return self.now


def quota(clock: Clock) -> VolumeQuota:
  """A quota on `clock` with the default throttles, spelled out for the tests."""
  return VolumeQuota(
    account='main', interval=600, step=500, threshold=2000, low_interval=60, clock=clock
  )


def logs(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str]]:
  """The (level, message) pairs logged so far."""
  return [(r.levelname, r.getMessage()) for r in caplog.records]


def test_logs_the_first_quota_then_throttles(caplog: pytest.LogCaptureFixture):
  """The first quota logs; small moves within the interval don't."""
  caplog.set_level(logging.INFO, logger=LOGGER)
  clock = Clock()
  q = quota(clock)
  q.update(10780)
  clock.now = 10
  q.update(10700)
  clock.now = 20
  q.update(10400)
  assert logs(caplog) == [('INFO', 'Lighter volume quota remaining: 10780 (main)')]
  assert q.remaining == 10400


def test_logs_again_after_the_interval(caplog: pytest.LogCaptureFixture):
  """An unchanged quota logs once the interval passed since the last log."""
  caplog.set_level(logging.INFO, logger=LOGGER)
  clock = Clock()
  q = quota(clock)
  q.update(10780)
  clock.now = 599
  q.update(10780)
  clock.now = 600
  q.update(10780)
  assert [m for _, m in logs(caplog)] == [
    'Lighter volume quota remaining: 10780 (main)'
  ] * 2


def test_logs_a_move_of_a_step_at_once(caplog: pytest.LogCaptureFixture):
  """A move of `step` from the last logged quota logs within the interval."""
  caplog.set_level(logging.INFO, logger=LOGGER)
  clock = Clock()
  q = quota(clock)
  q.update(10780)
  clock.now = 1
  q.update(10281)
  clock.now = 2
  q.update(10280)
  clock.now = 3
  q.update(10000)
  assert [m for _, m in logs(caplog)] == [
    'Lighter volume quota remaining: 10780 (main)',
    'Lighter volume quota remaining: 10280 (main)',
  ]


def test_warns_below_the_threshold_at_once_then_throttled(
  caplog: pytest.LogCaptureFixture,
):
  """Dropping below the threshold warns at once, then once per `low_interval`."""
  caplog.set_level(logging.INFO, logger=LOGGER)
  clock = Clock()
  q = quota(clock)
  q.update(2100)
  clock.now = 1
  q.update(1999)
  clock.now = 30
  q.update(1500)
  clock.now = 61
  q.update(1490)
  assert logs(caplog) == [
    ('INFO', 'Lighter volume quota remaining: 2100 (main)'),
    ('WARNING', 'Lighter volume quota remaining: 1999 (main, below 2000)'),
    ('WARNING', 'Lighter volume quota remaining: 1490 (main, below 2000)'),
  ]


def test_a_refilled_quota_logs_at_info(caplog: pytest.LogCaptureFixture):
  """Back above the threshold by a step, the quota logs at INFO again."""
  caplog.set_level(logging.INFO, logger=LOGGER)
  clock = Clock()
  q = quota(clock)
  q.update(1000)
  clock.now = 1
  q.update(5000)
  assert [level for level, _ in logs(caplog)] == ['WARNING', 'INFO']


def test_replies_without_a_quota_are_ignored(caplog: pytest.LogCaptureFixture):
  """The free transaction's reply carries no quota: nothing is noted or logged."""
  caplog.set_level(logging.INFO, logger=LOGGER)
  q = quota(Clock())
  q.record({'code': 200, 'tx_hash': 'h'})
  assert q.remaining is None and caplog.records == []


@dataclass
class Tx:
  """Accept transactions alone and in batches, reporting `remaining` quota."""

  remaining: int
  batches: list[list[Any]] = field(default_factory=list[list[Any]])

  @asynccontextmanager
  async def reserve_nonces(self, count: int) -> AsyncIterator[SimpleNamespace]:
    """Consecutive nonces from 0 on key 0."""
    yield SimpleNamespace(api_key_index=0, nonces=range(count))

  async def batch(self, signed: list[Any]) -> dict[str, Any]:
    """Accept a batch."""
    self.batches.append(signed)
    return {
      'code': 200,
      'tx_hash': [f'hash-{nonce}' for nonce in signed],
      'predicted_execution_time_ms': 1,
      'volume_quota_remaining': self.remaining,
    }


def order_tx(remaining: int) -> OrderTx:
  """A transaction whose lone `sendTx` reports `remaining` quota."""

  async def send() -> SendTxResponse:
    """Accept it alone."""
    return {
      'code': 200,
      'tx_hash': 'single',
      'predicted_execution_time_ms': datetime(2026, 1, 1, tzinfo=timezone.utc),
      'volume_quota_remaining': remaining,
    }

  return OrderTx(send=send, sign=lambda _key, nonce: cast(Any, nonce))


async def test_the_batcher_records_lone_and_batched_replies(
  caplog: pytest.LogCaptureFixture,
):
  """Both a lone `sendTx` and a `sendTxBatch` reply reach the account's quota."""
  caplog.set_level(logging.INFO, logger=LOGGER)
  tx = Tx(remaining=9000)
  batcher = TxBatcher(
    cast(Lighter, SimpleNamespace(tx=tx)), quota=VolumeQuota(account='main')
  )
  await batcher.submit(order_tx(10000))
  assert batcher.quota.remaining == 10000
  await asyncio.gather(*[batcher.submit(order_tx(0)) for _ in range(3)])
  assert len(tx.batches) == 1 and batcher.quota.remaining == 9000
  assert [m for _, m in logs(caplog)] == [
    'Lighter volume quota remaining: 10000 (main)',
    'Lighter volume quota remaining: 9000 (main)',
  ]
