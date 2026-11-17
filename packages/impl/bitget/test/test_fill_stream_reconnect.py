"""A UTA fills stream comes back after a service upgrade and after a lost login.

A fake Bitget private WebSocket keeps a login per connection, answers a private subscribe
without one with `30004`, and can announce a reset with `30033`, as the venue did on
2026-11-17, when `bitget:usdt:IOTXUSDT`'s trades stream could not start for an hour.
"""

from dataclasses import dataclass, field, replace
from datetime import timedelta
from decimal import Decimal
import asyncio
import json

import pytest
from typing_extensions import Any, AsyncIterator
from websockets.asyncio.server import Server, ServerConnection, serve
from typed_bitget import Bitget
from typed_bitget.core.auth import Credentials
from typed_bitget.core.transport.ws import session
from typed_bitget.core.transport.ws.uta import UtaSocketStreamClient

from tribulnation.bitget.core import SdkMixin
from tribulnation.bitget.market.impl import Cache
from tribulnation.bitget.market.perp_market import PerpMarket
from tribulnation.sdk.core import NetworkError
from tribulnation.sdk.market import Trade

ACCESS_KEY = 'fake-access'
SECRET = 'fake-secret'
PASSPHRASE = 'fake-passphrase'
"""Fake credentials; only ever sent to the local fake socket."""
SYMBOL = 'IOTXUSDT'
CONTRACT: dict[str, Any] = {
  'symbol': SYMBOL,
  'baseCoin': 'IOTX',
  'quoteCoin': 'USDT',
  'symbolType': 'perpetual',
  'maxLever': Decimal(50),
}
FILL_ARG = {'instType': 'UTA', 'topic': 'fill'}


@dataclass
class Conn:
  """One server-side connection."""

  ws: ServerConnection
  id: str
  logged_in: bool = False
  amnesiac: bool = False
  """Accepts logins but refuses every private subscribe with `30004`."""


@dataclass
class FakePrivateWs:
  """Bitget's UTA private WebSocket, reduced to logins and the `fill` topic."""

  conns: list[Conn] = field(default_factory=list[Conn])
  logins: list[str] = field(default_factory=list[str])

  async def handle(self, ws: ServerConnection):
    """Serve one connection."""
    conn = Conn(ws, f'conn-{len(self.conns)}')
    self.conns.append(conn)
    async for raw in ws:
      if raw == 'ping':
        await ws.send('pong')
        continue
      msg = json.loads(raw)
      arg = msg['args'][0] if msg['op'] != 'login' else None
      match msg['op']:
        case 'login':
          conn.logged_in = True
          self.logins.append(conn.id)
          reply: dict[str, Any] = {'event': 'login', 'code': '0', 'connId': conn.id}
        case 'subscribe' if conn.logged_in and not conn.amnesiac:
          reply = {'event': 'subscribe', 'arg': arg, 'connId': conn.id}
        case 'subscribe':
          reply = {
            'event': 'error',
            'code': 30004,
            'msg': 'User not logged in/User must be logged in',
            'connId': conn.id,
          }
        case _:
          reply = {'event': msg['op'], 'arg': arg, 'connId': conn.id}
      await ws.send(json.dumps(reply))

  async def fill(self, exec_id: str):
    """Push one IOTXUSDT fill on the latest connection."""
    row: dict[str, Any] = {
      'orderId': '1',
      'clientOid': '2',
      'execId': exec_id,
      'category': 'USDT-FUTURES',
      'symbol': SYMBOL,
      'orderType': 'limit',
      'side': 'buy',
      'holdSide': 'long',
      'execQty': '100',
      'execValue': '1',
      'execPrice': '0.01',
      'execPnl': '0',
      'tradeScope': 'maker',
      'feeDetail': [{'feeCoin': 'USDT', 'fee': '0.0002'}],
      'execTime': '1794831592000',
      'updatedTime': '1794831592000',
      'tradeSide': 'open',
      'execLinkId': exec_id,
      'isRPI': 'no',
    }
    push: dict[str, Any] = {'action': 'update', 'arg': FILL_ARG, 'data': [row], 'ts': 0}
    await self.conns[-1].ws.send(json.dumps(push))

  async def upgrade(self):
    """Forget the latest connection's login and announce its reset."""
    conn = self.conns[-1]
    conn.logged_in = False
    notice: dict[str, Any] = {
      'event': 'error',
      'code': 30033,
      'msg': 'Service upgrade in progress. Connection reset imminent. Please reconnect.',
    }
    await conn.ws.send(json.dumps(notice))


@pytest.fixture
async def venue() -> AsyncIterator[tuple[FakePrivateWs, Server]]:
  """The fake private socket, listening on a free local port."""
  fake = FakePrivateWs()
  async with serve(fake.handle, '127.0.0.1', 0) as srv:
    yield fake, srv


@pytest.fixture
async def market(
  venue: tuple[FakePrivateWs, Server], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[PerpMarket]:
  """A UTA IOTXUSDT market whose private socket is the fake."""
  _, srv = venue
  url = f'ws://127.0.0.1:{next(iter(srv.sockets)).getsockname()[1]}'
  monkeypatch.setattr(session, 'LOGIN_BACKOFF', timedelta(milliseconds=10))
  creds = Credentials(access_key=ACCESS_KEY, secret_key=SECRET, passphrase=PASSPHRASE)
  streams = UtaSocketStreamClient.new(
    public_url=url, private_url=url, credentials=creds, timeout=timedelta(seconds=1)
  )
  client = replace(
    Bitget.new(access_key=ACCESS_KEY, secret_key=SECRET, passphrase=PASSPHRASE),
    uta_streams_client=streams,
  )
  cache = Cache(account_id='bg', perp={'USDT-FUTURES': {SYMBOL: CONTRACT}})  # type: ignore[dict-item]
  async with streams:
    yield PerpMarket(
      account=SdkMixin(client=client, uta=True), cache=cache, symbol=SYMBOL
    )


async def first_fill(market: PerpMarket, fake: FakePrivateWs, exec_id: str) -> Trade:
  """Open the trades stream, have the venue push one fill, and read it."""
  async with market.trades_stream() as fills:
    await fake.fill(exec_id)
    return await asyncio.wait_for(anext(aiter(fills)), 1)


async def test_service_upgrade_then_restart(
  venue: tuple[FakePrivateWs, Server], market: PerpMarket
):
  """The upgrade notice ends the running stream; the restarted one gets fills again."""
  fake, _ = venue
  with pytest.raises(NetworkError):
    async with market.trades_stream() as fills:
      await fake.fill('before')
      assert (await anext(aiter(fills))).qty == Decimal(100)
      await fake.upgrade()
      await asyncio.wait_for(anext(aiter(fills)), 1)

  trade = await first_fill(market, fake, 'after')
  assert trade.id == 'after'
  assert fake.logins == ['conn-0', 'conn-1']


async def test_lost_login_on_a_live_connection(
  venue: tuple[FakePrivateWs, Server], market: PerpMarket
):
  """A connection that answers `30004` (same `connId`) is replaced and logged in anew."""
  fake, _ = venue
  assert (await first_fill(market, fake, 'before')).id == 'before'
  fake.conns[-1].amnesiac = True

  assert (await first_fill(market, fake, 'after')).id == 'after'
  assert fake.logins == ['conn-0', 'conn-1']
