"""Tests for structured asynchronous task ownership."""

import asyncio

import pytest

from tribulnation.sdk.core import RateLimited, managed_tasks

async def test_managed_tasks_preserves_direct_exception_and_cancels_sibling() -> None:
  """Preserve the awaited error while draining unfinished siblings."""
  error = RateLimited('limited')
  sibling_cancelled = asyncio.Event()

  async def fail() -> None:
    """Raise the expected error."""
    raise error

  async def block() -> None:
    """Block until task ownership cancels this coroutine."""
    try:
      await asyncio.Event().wait()
    finally:
      sibling_cancelled.set()

  tasks: tuple[asyncio.Future[None], ...] = ()
  with pytest.raises(RateLimited) as raised:
    async with managed_tasks((fail(), block())) as tasks:
      for completed in asyncio.as_completed(tasks):
        await completed

  assert raised.value is error
  assert sibling_cancelled.is_set()
  assert all(task.done() for task in tasks)

async def test_managed_tasks_supports_completion_order() -> None:
  """Expose owned tasks for completion-order consumption."""
  release = asyncio.Event()

  async def first():
    """Wait before returning the first value."""
    await release.wait()
    return 'first'

  async def second():
    """Return the second value immediately."""
    return 'second'

  values: list[str] = []
  async with managed_tasks((first(), second())) as tasks:
    for completed in asyncio.as_completed(tasks):
      value = await completed
      values.append(value)
      release.set()

  assert values == ['second', 'first']

async def test_managed_tasks_propagates_outer_cancellation_after_cleanup() -> None:
  """Cancel child work before propagating outer cancellation."""
  child_cancelled = asyncio.Event()

  async def child():
    """Block until canceled by task ownership."""
    try:
      await asyncio.Event().wait()
    finally:
      child_cancelled.set()

  async def parent():
    """Own one child while waiting indefinitely."""
    async with managed_tasks((child(),)):
      await asyncio.Event().wait()

  task = asyncio.create_task(parent())
  await asyncio.sleep(0)
  task.cancel()
  with pytest.raises(asyncio.CancelledError):
    await task

  assert child_cancelled.is_set()

async def test_managed_tasks_drains_sibling_exceptions() -> None:
  """Retrieve sibling exceptions without loop-level warnings."""
  errors: list[dict[str, object]] = []
  loop = asyncio.get_running_loop()
  previous_handler = loop.get_exception_handler()
  loop.set_exception_handler(lambda _loop, context: errors.append(context))

  async def fail(message: str):
    """Raise one sibling error."""
    raise RuntimeError(message)

  try:
    with pytest.raises(RuntimeError, match='first'):
      async with managed_tasks((fail('first'), fail('second'))) as tasks:
        await tasks[0]
    await asyncio.sleep(0)
  finally:
    loop.set_exception_handler(previous_handler)

  assert errors == []

async def test_managed_tasks_cleans_up_on_async_generator_close() -> None:
  """Cancel remaining work when an async generator is closed early."""
  sibling_cancelled = asyncio.Event()

  async def immediate():
    """Return the first generated value."""
    return 'value'

  async def block():
    """Block until generator cleanup cancels this task."""
    try:
      await asyncio.Event().wait()
    finally:
      sibling_cancelled.set()

  async def stream():
    """Yield owned task results in completion order."""
    async with managed_tasks((immediate(), block())) as tasks:
      for completed in asyncio.as_completed(tasks):
        yield await completed

  generator = stream()
  assert await anext(generator) == 'value'
  await generator.aclose()

  assert sibling_cancelled.is_set()

async def test_managed_tasks_accepts_no_awaitables() -> None:
  """Allow callers to own an empty task collection."""
  async with managed_tasks(()) as tasks:
    assert tasks == ()
