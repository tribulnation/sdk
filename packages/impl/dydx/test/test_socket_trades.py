"""Socket fills: frame parsing, the socket stream and racing in `'fastest'`."""

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing_extensions import Any, AsyncIterator, cast
import asyncio
import json

import pytest
from websockets.asyncio.server import ServerConnection, unix_serve
from typed_dydx.indexer.schemas import PerpetualMarket
from typed_dydx.protos.dydxprotocol import clob, subaccounts

from tribulnation.dydx.market.exchange import Exchange
from tribulnation.dydx.market.impl import socket_fills
from tribulnation.dydx.market.impl.dedup import FillDedup, FillRace
from tribulnation.dydx.market.impl.mixin import MarketMixin
from tribulnation.dydx.market.impl.node_fills import NodeFill, node_key
from tribulnation.dydx.market.impl.orders import (
  indexer_order_id,
  indexer_subaccount_id,
  serialize_id,
)
from tribulnation.dydx.market.impl.socket_fills import (
  FrameParser,
  SocketFill,
  SocketItem,
  SocketRevert,
  frame_adapter,
)
from tribulnation.dydx.market.impl.trades import indexer_key, trades_stream
from tribulnation.sdk.core import NetworkError, Subscription
from tribulnation.sdk.market import Trade

ADDRESS = 'dydx1039f5sxkl0t39vxcsnmlu62ly22typdap0zkyn'
OTHER = 'dydx1other'
BLOCK_TIME = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
MARKET = cast(
  PerpetualMarket,
  {
    'ticker': 'BTC-USD',
    'clobPairId': 0,
    'atomicResolution': -10,
    'quantumConversionExponent': -9,
    'stepBaseQuantums': 1_000_000,
    'subticksPerTick': 100_000,
  },
)
"""BTC-USD: 1e-10 BTC per quantum, 1e-5 USD per subtick."""


def order_id(
  client_id: int, *, owner: str = ADDRESS, number: int = 0
) -> dict[str, Any]:
  """A frame's order id on BTC-USD (short-term)."""
  return {
    'owner': owner,
    'number': number,
    'client_id': client_id,
    'order_flags': 0,
    'clob_pair_id': 0,
  }


def proto_id(client_id: int, *, owner: str = ADDRESS, number: int = 0) -> clob.OrderId:
  """The protocol order id of `order_id`."""
  return clob.OrderId(
    subaccount_id=subaccounts.SubaccountId(owner=owner, number=number),
    client_id=client_id,
    order_flags=0,
    clob_pair_id=0,
  )


def fill_frame(
  height: int = 10,
  *,
  index: int = 0,
  round: int = 0,
  level: str = 'committed',
  kind: str = 'match',
  taker: dict[str, Any] | None = None,
  maker: dict[str, Any] | None = None,
  liquidated: dict[str, Any] | None = None,
  offsetting: dict[str, Any] | None = None,
  taker_side: str = 'SELL',
  subticks: int | None = 6_000_000_000,
  quote_quantums: int | None = None,
) -> dict[str, Any]:
  """A daemon fill frame of 0.001 BTC at 60000 (by default our maker buy)."""
  return {
    'tag': 'fill',
    'level': level,
    'height': height,
    'round': round,
    'index': index,
    'op': 0,
    'kind': kind,
    'clob_pair_id': 0,
    'quantums': 10_000_000,
    'subticks': subticks,
    'quote_quantums': quote_quantums,
    'taker_side': taker_side,
    'taker': taker
    if taker is not None or kind != 'match'
    else order_id(9, owner=OTHER),
    'maker': maker if maker is not None or kind == 'deleveraging' else order_id(1),
    'liquidated': liquidated,
    'offsetting': offsetting,
    'is_final_settlement': False,
    'backfill': False,
    'block_time': 0,
    'proposal_at': 0,
    'complete_at': 0,
    'commit_at': 0,
    'sent_at': 0,
    'future_field': 'ignored',
  }


def parse(parser: FrameParser, *frames: dict[str, Any]) -> list[SocketItem]:
  """Parse raw frames."""
  return [
    item for f in frames for item in parser.parse(frame_adapter.validate_python(f))
  ]


def fills(items: list[SocketItem]) -> list[NodeFill]:
  """The fills among parsed items."""
  return [i.fill for i in items if isinstance(i, SocketFill)]


# ── Parsing ─────────────────────────────────────────────────────────────────


def test_maker_fill_of_ours():
  """Our maker order filled by someone's sell: a buy at our price, with the node's id."""
  [fill] = fills(parse(FrameParser(ADDRESS, 0), fill_frame()))
  assert (fill.kind, fill.side, fill.maker, fill.subticks, fill.quantums) == (
    'order',
    'BUY',
    True,
    6_000_000_000,
    10_000_000,
  )
  assert fill.order_id == proto_id(1)
  assert fill.id == f'10:{serialize_id(proto_id(1))}:0'
  assert fill.exec_mode == 7


def test_taker_fill_of_ours_and_self_trade():
  """As taker we take the taker's side; trading against our own child is both sides."""
  frame = fill_frame(
    taker=order_id(2, number=128), maker=order_id(1), taker_side='SELL'
  )
  got = fills(parse(FrameParser(ADDRESS, 0), frame))
  assert [(f.side, f.maker, f.subaccount) for f in got] == [
    ('SELL', False, 128),
    ('BUY', True, 0),
  ]


def test_other_owners_and_parents_are_not_ours():
  """Another owner's fill, or a subaccount of another parent, yields nothing."""
  parser = FrameParser(ADDRESS, 0)
  assert parse(parser, fill_frame(maker=order_id(1, owner=OTHER))) == []
  assert parse(parser, fill_frame(index=1, maker=order_id(1, number=1))) == []


def test_liquidated_and_deleveraged():
  """Liquidated: the liquidated side at the maker's price; deleveraging: both roles,
  priced from the quote amount."""
  parser = FrameParser(ADDRESS, 0)
  us: dict[str, Any] = {'owner': ADDRESS, 'number': 0}
  [liq] = fills(
    parse(
      parser,
      fill_frame(kind='liquidation', liquidated=us, maker=order_id(5, owner=OTHER)),
    )
  )
  assert (liq.kind, liq.side, liq.order_id, liq.subticks) == (
    'liquidated',
    'SELL',
    None,
    6_000_000_000,
  )
  delev = fill_frame(
    index=1,
    kind='deleveraging',
    liquidated=us,
    offsetting={'owner': ADDRESS, 'number': 128},
    taker_side='BUY',
    subticks=None,
    quote_quantums=60_000_000,
  )
  got = fills(parse(parser, delev))
  assert [(f.kind, f.side, f.maker, f.quote_quantums) for f in got] == [
    ('deleveraged', 'BUY', False, 60_000_000),
    ('offsetting', 'SELL', True, 60_000_000),
  ]


def test_unpriced_fill_is_left_to_other_sources(caplog: pytest.LogCaptureFixture):
  """A fill whose stateful maker the daemon could not price is skipped, with a warning."""
  assert parse(FrameParser(ADDRESS, 0), fill_frame(subticks=None)) == []
  assert 'no maker price' in caplog.text


def test_replays_after_a_block_are_skipped():
  """Fills of a complete height, or already read, are not emitted again."""
  parser = FrameParser(ADDRESS, 0)
  assert len(parse(parser, fill_frame(10))) == 1
  assert parse(parser, fill_frame(10)) == []  # same (height, round, index)
  parse(parser, {'tag': 'block', 'height': 10, 'fills': 1})
  assert parse(parser, fill_frame(10, index=5)) == []
  assert parser.last_block == 10 and parser.seen == set()


def test_revert_and_unknown_frames():
  """`revert` becomes an item; tags this client doesn't read are rejected by the adapter
  and skipped by the feed."""
  [revert] = parse(FrameParser(ADDRESS, 0), {'tag': 'revert', 'height': 10, 'round': 0})
  assert revert == SocketRevert(height=10, round=0)
  assert 'commit' not in socket_fills.FRAME_TAGS


def test_socket_node_and_indexer_keys_agree():
  """A socket fill keys like the node's and the indexer's copy of it."""
  [fill] = fills(parse(FrameParser(ADDRESS, 0), fill_frame()))
  indexer_fill: Any = {
    'createdAtHeight': 10,
    'orderId': indexer_order_id(proto_id(1)),
    'size': Decimal('0.0010'),
    'side': 'BUY',
    'subaccountId': indexer_subaccount_id(ADDRESS, 0),
    'clobPairId': 0,
  }
  assert node_key(fill, MARKET, address=ADDRESS) == indexer_key(indexer_fill)


def test_race_records_who_was_first_and_by_how_much():
  """Leads are per (first, second) pair, in milliseconds."""
  race = FillRace()
  dedup = FillDedup(race=race)
  key = node_key(
    fills(parse(FrameParser(ADDRESS, 0), fill_frame()))[0], MARKET, address=ADDRESS
  )
  assert dedup.admit('socket', key, at=1.0)
  assert not dedup.admit('node', key, at=1.05)
  assert not dedup.admit('indexer', key, at=1.2)
  assert race.wins == {'socket': 1}
  summary = {(lead['first'], lead['second']): lead['p50_ms'] for lead in race.summary()}
  assert summary == {
    ('socket', 'indexer'): pytest.approx(200),
    ('socket', 'node'): pytest.approx(50),
  }


def test_retract_lets_a_real_copy_through():
  """A retracted socket copy (its proposal reverted) no longer blocks the indexer's."""
  dedup = FillDedup()
  key = node_key(
    fills(parse(FrameParser(ADDRESS, 0), fill_frame()))[0], MARKET, address=ADDRESS
  )
  assert dedup.admit('socket', key)
  dedup.retract('socket', key)
  assert dedup.admit('indexer', key)


# ── Streams ─────────────────────────────────────────────────────────────────


class FakeDaemon:
  """A fill daemon on a unix socket that serves scripted frames per connection."""

  def __init__(self, path: Path, connections: list[list[dict[str, Any]]]):
    self.path = path
    self.connections = connections
    self.subscribes: list[dict[str, Any]] = []
    self.protocols: list[str | None] = []

  async def handler(self, ws: ServerConnection):
    """Read the subscribe frame, send this connection's frames, then close or idle."""
    self.protocols.append(ws.subprotocol)
    self.subscribes.append(json.loads(await ws.recv()))
    frames = self.connections.pop(0) if self.connections else []
    await ws.send(
      json.dumps(
        {
          'tag': 'hello',
          'protocol': socket_fills.PROTOCOL,
          'level': 'committed',
          'chain_id': 'x',
          'height': 0,
        }
      ).encode()
    )
    for frame in frames:
      await ws.send(json.dumps(frame).encode())
    if not self.connections:
      await ws.wait_closed()


def socket_market(
  path: str, *, indexer: AsyncIterator[Any] | None = None
) -> MarketMixin:
  """A BTC-USD market whose account sets `fill_socket` (and a fake indexer)."""
  shared = Exchange.new(address=ADDRESS, public=True, fill_socket=path).shared

  async def noop():
    """Nothing to release."""

  if indexer is not None:
    indexer_iter = indexer

    async def subscribe_indexer():
      """The fake indexer channel."""
      return indexer_iter, noop

    shared.parent_subaccount_subscriptions[0] = Subscription.of(subscribe_indexer)
  return MarketMixin(shared=shared, perpetual_market=MARKET)


async def take(stream: AsyncIterator[Trade], n: int) -> list[Trade]:
  """The first `n` trades, failing rather than hanging."""
  return [await asyncio.wait_for(anext(stream), 2) for _ in range(n)]


@pytest.fixture
def sock(tmp_path: Path) -> Path:
  """A short socket path (unix paths are limited to ~108 bytes)."""
  return tmp_path / 's.sock'


async def test_socket_stream_reads_frames_reconnects_and_reverses(
  sock: Path, monkeypatch: pytest.MonkeyPatch
):
  """Trades come from the daemon's frames; after a reconnection the feed resubscribes
  from the last complete height; a revert reverses a proposed trade."""
  monkeypatch.setattr(socket_fills, 'RECONNECT_MIN', 0)
  daemon = FakeDaemon(
    sock,
    [
      [fill_frame(10), {'tag': 'block', 'height': 10, 'fills': 1}],  # then closes
      [
        fill_frame(10),  # replayed: skipped
        fill_frame(11, level='proposed'),
        {'tag': 'revert', 'height': 11, 'round': 0},
      ],
    ],
  )
  async with unix_serve(
    daemon.handler, str(sock), subprotocols=[socket_fills.PROTOCOL]
  ):
    market = socket_market(str(sock))
    settings: Any = {'dydx': {'trades_source': 'socket'}}
    async with trades_stream(market, settings=settings) as stream:
      got = await take(aiter(stream), 3)
  assert [(t.qty, cast(dict[str, Any], t.details)['level']) for t in got] == [
    (Decimal('0.001'), 'committed'),
    (Decimal('0.001'), 'proposed'),
    (Decimal('-0.001'), 'proposed'),
  ]
  assert got[0].price == Decimal('60000') and got[0].time is None
  assert cast(dict[str, Any], got[2].details)['revert'] is True
  assert [s['from_height'] for s in daemon.subscribes] == [0, 10]
  assert daemon.protocols == [socket_fills.PROTOCOL] * 2


def indexer_message(height: int = 10) -> dict[str, Any]:
  """The indexer's copy of `fill_frame(height)`."""
  return {
    'fills': [
      {
        'id': f'indexer-{height}',
        'ticker': 'BTC-USD',
        'side': 'BUY',
        'price': Decimal('60000'),
        'size': Decimal('0.001'),
        'createdAt': BLOCK_TIME,
        'createdAtHeight': height,
        'liquidity': 'MAKER',
        'type': 'LIMIT',
        'orderId': indexer_order_id(proto_id(1)),
        'subaccountId': indexer_subaccount_id(ADDRESS, 0),
        'clobPairId': 0,
      }
    ]
  }


async def test_fastest_races_socket_and_indexer(sock: Path):
  """The socket's copy wins, the indexer's is dropped, and the race is recorded."""
  indexer_ready = asyncio.Event()

  async def indexer() -> AsyncIterator[Any]:
    """The indexer, later than the socket."""
    await indexer_ready.wait()
    yield indexer_message(10)
    yield indexer_message(11)
    await asyncio.Event().wait()

  daemon = FakeDaemon(sock, [[fill_frame(10)]])
  async with unix_serve(
    daemon.handler, str(sock), subprotocols=[socket_fills.PROTOCOL]
  ):
    market = socket_market(str(sock), indexer=indexer())
    async with trades_stream(
      market, settings={'dydx': {'trades_source': 'fastest'}}
    ) as stream:
      it = aiter(stream)
      [first] = await take(it, 1)
      indexer_ready.set()
      [second] = await take(it, 1)
  assert cast(dict[str, Any], first.details)['source'] == 'socket'
  assert second.id == 'indexer-11'  # height 10's indexer copy was dropped
  race = market.shared.fill_race
  assert race is not None and race.wins == {'socket': 1, 'indexer': 1}
  assert [(lead['first'], lead['second']) for lead in race.summary()] == [
    ('socket', 'indexer')
  ]


async def test_fastest_drops_a_failing_socket_and_keeps_the_indexer(
  monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
  """A socket source that fails is dropped with a warning; indexer fills keep coming."""

  async def broken() -> AsyncIterator[SocketItem]:
    """A socket feed that fails at once."""
    raise RuntimeError('daemon gone')
    yield

  async def indexer() -> AsyncIterator[Any]:
    """The indexer."""
    await asyncio.sleep(0.05)
    yield indexer_message(10)
    await asyncio.Event().wait()

  market = socket_market('/nonexistent.sock', indexer=indexer())

  async def noop():
    """Nothing to release."""

  async def subscribe_socket():
    """The broken feed."""
    return broken(), noop

  market.shared.socket_subscription = Subscription.of(subscribe_socket)
  async with trades_stream(
    market, settings={'dydx': {'trades_source': 'fastest'}}
  ) as stream:
    [trade] = await take(aiter(stream), 1)
  assert trade.id == 'indexer-10'
  assert 'racing without them' in caplog.text


async def test_fastest_fails_when_the_indexer_fails(sock: Path):
  """The indexer is the floor: its failure ends the stream."""

  async def indexer() -> AsyncIterator[Any]:
    """An indexer channel that fails."""
    raise NetworkError('indexer down')
    yield

  daemon = FakeDaemon(sock, [[]])
  async with unix_serve(
    daemon.handler, str(sock), subprotocols=[socket_fills.PROTOCOL]
  ):
    market = socket_market(str(sock), indexer=indexer())
    async with trades_stream(
      market, settings={'dydx': {'trades_source': 'fastest'}}
    ) as stream:
      with pytest.raises(NetworkError, match='indexer down'):
        await asyncio.wait_for(anext(aiter(stream)), 2)


async def test_socket_needs_fill_socket():
  """`'socket'` without `fill_socket` says what is missing; `'fastest'` needs a node or
  a socket."""
  market = MarketMixin(
    shared=Exchange.new(address=ADDRESS, public=True).shared, perpetual_market=MARKET
  )
  for source, match in [('socket', 'fill_socket'), ('fastest', 'fill_socket')]:
    with pytest.raises(ValueError, match=match):
      async with trades_stream(market, settings={'dydx': {'trades_source': source}}):  # type: ignore[typeddict-item]
        pass


async def test_account_fill_source_is_the_default(sock: Path):
  """`accounts.Dydx.fill_source`/`fill_socket` reach the client and pick the source when
  the call names none."""
  from tribulnation.sdk import MarketSDK, accounts

  sdk = MarketSDK(
    {
      'd': accounts.Dydx(
        address=ADDRESS, public=True, fill_source='socket', fill_socket=str(sock)
      ),
      'plain': accounts.Dydx(address=ADDRESS, public=True),
    }
  )
  exchange = await sdk.all['d'].perp_exchange('perp')
  plain = await sdk.all['plain'].perp_exchange('perp')
  assert isinstance(exchange, Exchange) and isinstance(plain, Exchange)
  assert (exchange.shared.fill_source, exchange.shared.fill_socket) == (
    'socket',
    str(sock),
  )
  assert (plain.shared.fill_source, plain.shared.fill_socket) == (None, None)
  daemon = FakeDaemon(sock, [[fill_frame(10)]])
  async with unix_serve(
    daemon.handler, str(sock), subprotocols=[socket_fills.PROTOCOL]
  ):
    market = MarketMixin(shared=exchange.shared, perpetual_market=MARKET)
    async with trades_stream(market) as stream:
      [trade] = await take(aiter(stream), 1)
  assert cast(dict[str, Any], trade.details)['source'] == 'socket'
