"""Subscriptions on the client's one `/stream` connection that survive their consumers.

The connection is shared by every stream of the client (in a gateway, by every task), and
the server keeps a channel subscribed until it is told otherwise or the connection drops.
A subscription the server holds but no local stream reads is an orphan: every later
subscribe to that channel is refused with `30003` ("Already Subscribed to : <channel>")
for as long as the connection lives. Orphans appear when a subscribe is cancelled or times
out after its frame was sent (the server registers it anyway), or when an unsubscribe is
cancelled before its frame is sent or times out. `channel` closes both ends: releases run
to completion even when the consumer is cancelled, and a refused subscribe drops the
orphan and subscribes again.
"""

from dataclasses import replace
import asyncio
import logging

from typing_extensions import Any, Awaitable, Callable, TypeVar
from typed_core.util import Stream, StreamManager
from typed_lighter import Lighter
from typed_lighter.core.envelope import error_code
from typed_lighter.core.exc import BadRequest

T = TypeVar('T')

log = logging.getLogger(__name__)

NOT_SUBSCRIBED = 30002
"""The server holds no subscription to the channel being unsubscribed."""
ALREADY_SUBSCRIBED = 30003
"""The server already holds a subscription to the channel being subscribed."""


async def drop_orphan(client: Lighter, channel: str):
  """Unsubscribe `channel` on the connection, for a subscription no local stream reads.

  Args:
    client: The client whose connection holds the orphan.
    channel: Slash-form channel (`account_market/0/476`).
  """
  try:
    await client.ws.conn.request_unsubscription(channel)
  except BadRequest as exc:
    # Released meanwhile (e.g. a late unsubscribe landed): nothing left to drop.
    if error_code(exc) != NOT_SUBSCRIBED:
      raise


async def subscribe(
  client: Lighter, channel: str, manager: StreamManager[T, Any, Any]
) -> Stream[T, Any, Any]:
  """Subscribe; when the connection holds an orphaned subscription, drop it and retry.

  `typed_core` refuses a second local subscription to a channel before asking the server,
  so a `30003` reply means no stream on this connection reads the channel. The retry
  starts from a fresh snapshot, which `order_book` and `account_market` readers need.

  Args:
    client: The client `manager` subscribes through.
    channel: Slash-form channel `manager` subscribes to.
    manager: The typed subscription; connected once, or twice after an orphan.
  """
  try:
    return await manager
  except BadRequest as exc:
    if error_code(exc) == ALREADY_SUBSCRIBED:
      log.warning(
        'Lighter %s: the connection kept a subscription no stream reads; resubscribing',
        channel,
      )
      await drop_orphan(client, channel)
      return await manager
    raise


def report_failure(channel: str) -> Callable[['asyncio.Future[Any]'], None]:
  """A done-callback logging a failed release, so a detached one is never silent."""

  def report(task: 'asyncio.Future[Any]'):
    """Log the release's exception, if it raised one."""
    if not task.cancelled() and (exc := task.exception()) is not None:
      log.warning(
        'Lighter %s: unsubscribe failed (%r); the next subscribe drops the orphan',
        channel,
        exc,
      )

  return report


def shielded(
  channel: str, unsubscribe: Callable[[], Awaitable[Any]]
) -> Callable[[], Awaitable[Any]]:
  """`unsubscribe`, run to completion even when its caller is cancelled.

  A consumer cancelled while leaving would otherwise abort the unsubscribe before its
  frame is sent (it waits for the connection's request lock first), leaving an orphan.

  Args:
    channel: Slash-form channel, for the log.
    unsubscribe: The typed stream's unsubscribe.
  """

  async def release() -> Any:
    """Unsubscribe in a task of its own, and wait for it unless cancelled."""
    task = asyncio.ensure_future(unsubscribe())
    task.add_done_callback(report_failure(channel))
    return await asyncio.shield(task)

  return release


def channel(
  client: Lighter, name: str, manager: StreamManager[T, Any, Any]
) -> StreamManager[T, Any, Any]:
  """`manager`, subscribing past orphans and releasing even when cancelled.

  Args:
    client: The client `manager` subscribes through.
    name: Slash-form channel `manager` subscribes to (`ticker/0`).
    manager: The typed subscription.
  """

  async def connect() -> Stream[T, Any, Any]:
    """Subscribe, and shield the stream's unsubscribe."""
    stream = await subscribe(client, name, manager)
    return replace(stream, unsubscribe=shielded(name, stream.unsubscribe))

  return StreamManager(connect)
