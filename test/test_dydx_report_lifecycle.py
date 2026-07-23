"""Tests for dYdX reporting client lifecycle."""

from typing import Any, cast
import asyncio

from tribulnation.dydx.report.main import Report
from tribulnation.dydx.report.snapshots import Snapshots

class FakeContext:
  """Record asynchronous context manager calls."""
  def __init__(self):
    self.entered = 0
    self.exits = []

  async def __aenter__(self):
    self.entered += 1
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    self.exits.append((exc_type, exc_value, traceback))

def test_snapshots_owns_client_lifecycle():
  """Snapshots enters and exits its dYdX client."""
  client = FakeContext()
  snapshots = Snapshots(address='dydx1test', client=cast(Any, client))

  async def use_snapshots():
    async with snapshots:
      assert client.entered == 1

  asyncio.run(use_snapshots())

  assert len(client.exits) == 1
  assert client.exits[0][:2] == (None, None)

def test_report_manages_implementations_on_exception():
  """Report exits both implementations when its context raises."""
  history = FakeContext()
  snapshots = FakeContext()
  report = Report(
    history_impl=cast(Any, history),
    snapshots_impl=cast(Any, snapshots),
  )

  async def use_report():
    try:
      async with report:
        assert history.entered == 1
        assert snapshots.entered == 1
        raise RuntimeError('test failure')
    except RuntimeError:
      pass

  asyncio.run(use_report())

  assert len(history.exits) == 1
  assert len(snapshots.exits) == 1
  assert history.exits[0][0] is RuntimeError
  assert snapshots.exits[0][0] is RuntimeError
