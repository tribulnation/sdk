"""A consumer leaving the shared `/stream` connection never locks its channel for the next.

A fake Lighter server keeps per-connection subscriptions and refuses a second subscribe
to a held channel with `30003`, as the venue does. Each test leaves the server holding
a channel no local stream reads (the 2026-11-17 incident), then subscribes again.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import asyncio
import json

import pytest
from typing_extensions import Any, AsyncIterator, cast
from websockets.asyncio.server import Server, ServerConnection, serve
from typed_lighter import Lighter
from typed_lighter.core.transport.ws import SocketClient
from typed_lighter.streams import Streams

from tribulnation.lighter.core import Shared
from tribulnation.lighter.market import history
from tribulnation.sdk.core import BadRequest
from tribulnation.sdk.market import Trade

ACCOUNT = 758234
MARKET = 0
CHANNEL = f'account_market:{MARKET}:{ACCOUNT}'
TIMEOUT = timedelta(seconds=0.3)


@dataclass
class FakeLighter:
  """A `/stream` server: per-connection subscriptions, `30002`/`30003` refusals."""

  subscribed: set[str] = field(default_factory=set[str])
  """Colon channels the (single) connection holds."""
  conns: list[ServerConnection] = field(default_factory=list[ServerConnection])
  refused: list[int] = field(default_factory=list[int])
  """Codes of the error frames sent."""
  subscribe_delay: float = 0
  """Seconds before registering and acking a subscribe."""
  drop_unsubscribes: int = 0
  """How many unsubscribe frames to ignore (lost on the way)."""

  async def handle(self, ws: ServerConnection):
    """Serve one connection."""
    self.conns.append(ws)
    await ws.send(json.dumps({'type': 'connected', 'session_id': 'x'}))
    async for raw in ws:
      msg = json.loads(raw)
      channel = str(msg.get('channel', '')).replace('/', ':')
      match msg['type']:
        case 'subscribe':
          await asyncio.sleep(self.subscribe_delay)
          await self.subscribe(ws, channel)
        case 'unsubscribe':
          await self.unsubscribe(ws, channel)

  async def refuse(self, ws: ServerConnection, code: int, message: str):
    """Send an error frame, as the venue does: no type, channel or id."""
    self.refused.append(code)
    await ws.send(json.dumps({'error': {'code': code, 'message': message}}))

  async def subscribe(self, ws: ServerConnection, channel: str):
    """Register and send the snapshot, or refuse a held channel."""
    if channel in self.subscribed:
      await self.refuse(ws, 30003, f'Already Subscribed to : {channel}')
    else:
      self.subscribed.add(channel)
      await ws.send(json.dumps(frame('subscribed', [])))

  async def unsubscribe(self, ws: ServerConnection, channel: str):
    """Release and ack, refuse a channel not held, or lose the frame."""
    if self.drop_unsubscribes > 0:
      self.drop_unsubscribes -= 1
    elif channel in self.subscribed:
      self.subscribed.discard(channel)
      await ws.send(json.dumps({'type': 'unsubscribed', 'channel': channel}))
    else:
      await self.refuse(ws, 30002, f'Not Subscribed to : {channel}')

  async def fill(self, trade_id: str):
    """Push a fill to the held channel."""
    assert CHANNEL in self.subscribed
    await self.conns[-1].send(json.dumps(frame('update', [trade_row(trade_id)])))


def frame(kind: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
  """An `account_market` frame (unvalidated: only what the fills reader needs)."""
  return {
    'type': f'{kind}/account_market',
    'channel': CHANNEL,
    'account': ACCOUNT,
    'trades': trades,
  }


def trade_row(trade_id: str) -> dict[str, Any]:
  """A fill where the account is the bid."""
  return {
    'trade_id_str': trade_id,
    'ask_account_id': 1,
    'bid_account_id': ACCOUNT,
    'ask_client_id_str': '0',
    'bid_client_id_str': '7',
    'price': '1',
    'size': '2',
    'timestamp': 0,
    'is_maker_ask': True,
  }


def no_fee(t: Any, account: int) -> Trade.Fee:
  """A zero fee; fees are not under test."""
  return Trade.Fee(amount=Decimal(0), asset='3')


class Tokens:
  """A token source that needs no key."""

  account_index = ACCOUNT
  scope = 'read'

  def token(self) -> str:
    """A placeholder token; the fake server does not check it."""
    return 'token'


@pytest.fixture
async def server() -> AsyncIterator[tuple[FakeLighter, Server]]:
  """The fake venue, listening on a free local port."""
  venue = FakeLighter()
  async with serve(venue.handle, '127.0.0.1', 0) as srv:
    yield venue, srv


@pytest.fixture
async def shared(server: tuple[FakeLighter, Server]) -> AsyncIterator[Shared]:
  """A shared owner over a real typed `/stream` connection to the fake venue."""
  _, srv = server
  port = next(iter(srv.sockets)).getsockname()[1]
  ws = SocketClient.new(
    f'ws://127.0.0.1:{port}',
    tokens=cast(Any, Tokens()),
    validate=False,
    timeout=TIMEOUT,
  )
  client = SimpleNamespace(ws=ws, streams=Streams(client=ws), account_index=ACCOUNT)
  async with ws:
    yield Shared(client=cast(Lighter, client))


def stream(shared: Shared):
  """The account's fills stream on the market, as `trades_stream` opens it."""
  return history.trades_stream(shared, MARKET, fee=no_fee)


async def first_fill(shared: Shared, venue: FakeLighter, trade_id: str) -> Trade:
  """Subscribe, have the venue push one fill, and read it."""
  async with stream(shared) as fills:
    await venue.fill(trade_id)
    return await asyncio.wait_for(anext(aiter(fills)), 1)


async def test_lost_unsubscribe_does_not_lock_the_channel(
  server: tuple[FakeLighter, Server], shared: Shared
):
  """A consumer dies and its unsubscribe never lands; the next consumer still reads fills."""
  venue, _ = server
  venue.drop_unsubscribes = 1
  with pytest.raises(RuntimeError, match='consumer crashed'):
    async with stream(shared):
      raise RuntimeError('consumer crashed')
  assert venue.subscribed == {CHANNEL}

  fill = await first_fill(shared, venue, 'after-restart')
  assert fill.id == 'after-restart'
  assert venue.refused == [30003]
  assert len(venue.conns) == 1


async def test_cancelled_subscribe_does_not_lock_the_channel(
  server: tuple[FakeLighter, Server], shared: Shared
):
  """A consumer cancelled while its subscribe is in flight leaves the venue holding the
  channel; the next consumer subscribes past it."""
  venue, _ = server
  venue.subscribe_delay = 0.1

  async def consume():
    """Read fills forever."""
    async with stream(shared) as fills:
      async for _ in fills:
        pass

  task = asyncio.create_task(consume())
  await asyncio.sleep(0.05)
  task.cancel()
  with pytest.raises(asyncio.CancelledError):
    await task
  await asyncio.sleep(0.1)
  assert venue.subscribed == {CHANNEL}

  venue.subscribe_delay = 0
  fill = await first_fill(shared, venue, 'after-cancel')
  assert fill.id == 'after-cancel'
  assert venue.refused == [30003]


async def test_cancelled_release_still_unsubscribes(
  server: tuple[FakeLighter, Server], shared: Shared
):
  """A consumer cancelled again while its unsubscribe waits its turn on the shared
  connection still releases the channel."""
  venue, _ = server
  entered = asyncio.Event()

  async def consume():
    """Hold the stream until cancelled."""
    async with stream(shared):
      entered.set()
      await asyncio.Event().wait()

  task = asyncio.create_task(consume())
  await entered.wait()
  # Another subscribe or unsubscribe in flight on the connection holds its request lock.
  async with shared.client.ws.conn.exchange_lock:
    task.cancel()
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
      await task
  await asyncio.sleep(0.1)
  assert venue.subscribed == set()

  assert (await first_fill(shared, venue, 'clean')).id == 'clean'
  assert venue.refused == []


async def test_last_consumer_out_releases_the_channel(
  server: tuple[FakeLighter, Server], shared: Shared
):
  """Consumers share one subscription; it is released when the last one leaves."""
  venue, _ = server
  async with stream(shared) as first:
    async with stream(shared) as second:
      await venue.fill('shared')
      assert (await anext(aiter(first))).id == 'shared'
      assert (await anext(aiter(second))).id == 'shared'
    assert venue.subscribed == {CHANNEL}
    await venue.fill('still')
    assert (await anext(aiter(first))).id == 'still'
  await asyncio.sleep(0.05)
  assert venue.subscribed == set()
  assert venue.refused == []


async def test_other_refusals_still_raise(
  server: tuple[FakeLighter, Server], shared: Shared
):
  """Only `30003` is healed; any other refusal reaches the consumer."""
  venue, _ = server

  async def invalid(ws: ServerConnection, channel: str):
    """Refuse every subscribe as an invalid channel."""
    await venue.refuse(ws, 30005, f'Invalid Channel: {channel}')

  venue.subscribe = invalid  # type: ignore[method-assign]
  with pytest.raises(BadRequest):
    async with stream(shared):
      pass
  assert venue.refused == [30005]
