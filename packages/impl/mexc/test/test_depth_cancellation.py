"""Pending MEXC depth reads belong to the reconstruction task that created them."""

import asyncio

import pytest

from tribulnation.mexc.market.impl.depth import DepthUpdate, receive_update


class RecordingQueue(asyncio.Queue[DepthUpdate]):
  """Expose the pending queue getter without relying on timing or task names."""

  def __init__(self):
    """Record when the receiver has started its child queue read."""
    super().__init__()
    self.started = asyncio.Event()
    self.getter: asyncio.Task[object] | None = None

  async def get(self) -> DepthUpdate:
    """Record the task owning the blocking read."""
    self.getter = asyncio.current_task()
    self.started.set()
    return await super().get()


async def test_cancelled_depth_receive_finishes_child_queue_read():
  """Unsubscribing while reconstruction awaits another diff leaves no orphan."""
  queue = RecordingQueue()

  async def collect():
    """Represent the independent update collector without network I/O."""
    await asyncio.Event().wait()

  collector = asyncio.create_task(collect())
  receiver = asyncio.create_task(receive_update(queue, collector))
  await queue.started.wait()
  getter = queue.getter
  assert getter is not None
  try:
    receiver.cancel()
    with pytest.raises(asyncio.CancelledError):
      await receiver
    assert getter.done()
    assert not collector.done()
  finally:
    receiver.cancel()
    getter.cancel()
    collector.cancel()
    await asyncio.gather(receiver, getter, collector, return_exceptions=True)
