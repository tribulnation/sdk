"""Our fills from a local fill daemon's unix socket (`trades_source='socket'`).

The daemon (one per host, not part of the SDK) publishes every fill of every block, as
raw protocol fields, on a WebSocket over a unix socket: subprotocol
`tribulnation-dydx-fills.v1`, one JSON object per binary frame, kind in `tag`. Whether fills arrive at proposal or at
commit time is the daemon's setting; every frame says its `level`, and a `revert` frame
voids a proposal that did not commit. `FrameParser` picks our fills out of the frames,
without I/O; `SocketFeed` reads the socket, reconnecting forever.
"""

from typing_extensions import (
  TYPE_CHECKING,
  Annotated,
  AsyncGenerator,
  Literal,
  TypedDict,
)
from dataclasses import dataclass, field
import asyncio
import json
import logging

import pydantic
from websockets.asyncio.client import unix_connect
from typed_dydx.indexer.schemas import PerpetualMarket
from typed_dydx.protos.dydxprotocol import clob, subaccounts
from tribulnation.sdk.core import Subscription
from tribulnation.sdk.market import Trade

from .node_fills import (
  EXEC_MODE_FINALIZE,
  FillKey,
  FillKind,
  NodeFill,
  Side,
  base_size,
  fill_price,
)
from .orders import MAX_SUBACCOUNT, serialize_id

if TYPE_CHECKING:
  from .mixin import Shared

log = logging.getLogger(__name__)

PROTOCOL = 'tribulnation-dydx-fills.v1'
"""WebSocket subprotocol of the daemon's frames."""
RECONNECT_MIN = 0.5
"""Seconds before the first reconnection attempt."""
RECONNECT_MAX = 10.0
"""Cap of the exponential reconnection backoff, in seconds."""

Level = Literal['proposed', 'committed']


class OrderIdFrame(TypedDict):
  owner: str
  number: int
  client_id: int
  order_flags: int
  clob_pair_id: int


class SubaccountFrame(TypedDict):
  owner: str
  number: int


class FillFrame(TypedDict):
  """One fill of a block: a maker fill of a match or liquidation, or one deleveraging fill."""

  tag: Literal['fill']
  level: Level
  height: int
  round: int
  index: int
  """The fill's position among its block's fills."""
  kind: Literal['match', 'liquidation', 'deleveraging']
  clob_pair_id: int
  """The market; for deleveraging, the perpetual id (equal on dYdX mainnet)."""
  quantums: int
  subticks: int | None
  """The maker order's price; `None` for deleveraging and when the daemon could not
  resolve a stateful maker order."""
  quote_quantums: int | None
  """Deleveraging only: absolute quote amount."""
  taker_side: Literal['BUY', 'SELL', '']
  """The taker's side; the liquidated side for liquidations and deleveraging."""
  taker: OrderIdFrame | None
  maker: OrderIdFrame | None
  liquidated: SubaccountFrame | None
  offsetting: SubaccountFrame | None


class RevertFrame(TypedDict):
  """The proposal of this height and round did not commit: its fills are void."""

  tag: Literal['revert']
  height: int
  round: int


class BlockFrame(TypedDict):
  """Every fill of this committed block is published."""

  tag: Literal['block']
  height: int


class HelloFrame(TypedDict):
  tag: Literal['hello']
  protocol: str
  level: Level


class StatusFrame(TypedDict):
  tag: Literal['status']
  peers: int
  height: int


Frame = Annotated[
  FillFrame | RevertFrame | BlockFrame | HelloFrame | StatusFrame,
  pydantic.Field(discriminator='tag'),
]
frame_adapter: pydantic.TypeAdapter[Frame] = pydantic.TypeAdapter(Frame)
FRAME_TAGS = {'fill', 'revert', 'block', 'hello', 'status'}
"""Tags this client reads; others (e.g. `commit`) are skipped."""


@dataclass(frozen=True, kw_only=True)
class SocketFill:
  """One fill of ours from the socket."""

  fill: NodeFill
  level: Level
  round: int


@dataclass(frozen=True, kw_only=True)
class SocketRevert:
  """Fills of ours published for `(height, round)` are void."""

  height: int
  round: int


SocketItem = SocketFill | SocketRevert


def opposite(side: Side) -> Side:
  """The other side."""
  return 'SELL' if side == 'BUY' else 'BUY'


def protocol_order_id(o: OrderIdFrame) -> clob.OrderId:
  """The protocol order id of a frame's order id."""
  return clob.OrderId(
    subaccount_id=subaccounts.SubaccountId(owner=o['owner'], number=o['number']),
    client_id=o['client_id'],
    order_flags=o['order_flags'],
    clob_pair_id=o['clob_pair_id'],
  )


@dataclass
class FrameParser:
  """Pick our fills out of the daemon's frames, one connection after another.

  Fill ids are synthetic and follow the node feed's scheme (`<height>:<subject>:<n>`,
  `FillParser`), so a fill gets the same id from the socket as from a full node. Frames
  of heights already complete (a `block` frame seen) are skipped, so a reconnection
  that replays from `last_block` emits nothing twice.
  """

  address: str
  parent: int
  """Parent subaccount; we own it and its children `parent + 128 * k`."""
  last_block: int = 0
  """Highest height whose `block` frame was read."""
  counts: dict[tuple[int, str], int] = field(default_factory=dict[tuple[int, str], int])
  """Fills per `(height, subject)` above `last_block`."""
  seen: set[tuple[int, int, int]] = field(default_factory=set[tuple[int, int, int]])
  """`(height, round, index)` of fill frames read above `last_block`."""

  def ours(self, owner: str, number: int) -> bool:
    """Whether a subaccount is the parent or one of its children."""
    return (
      owner == self.address and number % 128 == self.parent and number <= MAX_SUBACCOUNT
    )

  def next_id(self, height: int, subject: str) -> str:
    """The synthetic id of the next fill of `subject` in `height`."""
    n = self.counts.get((height, subject), 0)
    self.counts[(height, subject)] = n + 1
    return f'{height}:{subject}:{n}'

  def parse(self, frame: Frame) -> list[SocketItem]:
    """Our items in one frame."""
    match frame['tag']:
      case 'fill':
        key = (frame['height'], frame['round'], frame['index'])
        if frame['height'] <= self.last_block or key in self.seen:
          return []
        self.seen.add(key)
        return list(self.fills(frame))
      case 'revert':
        return [SocketRevert(height=frame['height'], round=frame['round'])]
      case 'block':
        if frame['height'] > self.last_block:
          self.last_block = frame['height']
          self.seen = {k for k in self.seen if k[0] > self.last_block}
          self.counts = {k: v for k, v in self.counts.items() if k[0] > self.last_block}
        return []
      case 'hello':
        if frame['protocol'] != PROTOCOL:
          log.warning(
            'dYdX fill daemon speaks %s, expected %s', frame['protocol'], PROTOCOL
          )
        return []
      case 'status':
        return []

  def item(
    self,
    frame: FillFrame,
    *,
    kind: FillKind,
    subaccount: int,
    order_id: clob.OrderId | None,
    side: Side,
    maker: bool,
    subject: str,
  ) -> SocketFill:
    """A fill of ours from a fill frame."""
    height = frame['height']
    fill = NodeFill(
      height=height,
      # Proposed fills are not finalized; 0 marks them as optimistic.
      exec_mode=EXEC_MODE_FINALIZE if frame['level'] == 'committed' else 0,
      clob_pair_id=frame['clob_pair_id'],
      kind=kind,
      subaccount=subaccount,
      order_id=order_id,
      side=side,
      quantums=frame['quantums'],
      subticks=frame['subticks'],
      quote_quantums=frame['quote_quantums'],
      maker=maker,
      id=self.next_id(height, subject),
    )
    return SocketFill(fill=fill, level=frame['level'], round=frame['round'])

  def fills(self, frame: FillFrame):
    """Our fills in a fill frame: up to one per side."""
    taker_side = frame['taker_side']
    if taker_side == '':
      log.warning('dYdX socket fill at %d without a side; skipped', frame['height'])
      return
    if frame['kind'] != 'deleveraging' and frame['subticks'] is None:
      if self.names_us(frame):
        log.warning(
          'dYdX socket fill of ours at %d has no maker price; left to other sources',
          frame['height'],
        )
      return
    taker, maker = frame['taker'], frame['maker']
    liquidated, offsetting = frame['liquidated'], frame['offsetting']
    perpetual = frame['clob_pair_id']
    if taker is not None and self.ours(taker['owner'], taker['number']):
      order_id = protocol_order_id(taker)
      yield self.item(
        frame,
        kind='order',
        subaccount=taker['number'],
        order_id=order_id,
        side=taker_side,
        maker=False,
        subject=serialize_id(order_id),
      )
    if (
      frame['kind'] == 'liquidation'
      and liquidated is not None
      and self.ours(liquidated['owner'], liquidated['number'])
    ):
      number = liquidated['number']
      yield self.item(
        frame,
        kind='liquidated',
        subaccount=number,
        order_id=None,
        side=taker_side,
        maker=False,
        subject=f'{number}:liquidated:{perpetual}',
      )
    if maker is not None and self.ours(maker['owner'], maker['number']):
      order_id = protocol_order_id(maker)
      yield self.item(
        frame,
        kind='order',
        subaccount=maker['number'],
        order_id=order_id,
        side=opposite(taker_side),
        maker=True,
        subject=serialize_id(order_id),
      )
    if frame['kind'] == 'deleveraging':
      roles: list[
        tuple[Literal['deleveraged', 'offsetting'], SubaccountFrame | None]
      ] = [
        ('deleveraged', liquidated),
        ('offsetting', offsetting),
      ]
      for kind, sub in roles:
        if sub is not None and self.ours(sub['owner'], sub['number']):
          number = sub['number']
          yield self.item(
            frame,
            kind=kind,
            subaccount=number,
            order_id=None,
            side=taker_side if kind == 'deleveraged' else opposite(taker_side),
            maker=kind == 'offsetting',
            subject=f'{number}:{kind}:{perpetual}',
          )

  def names_us(self, frame: FillFrame) -> bool:
    """Whether any subaccount of the frame is ours."""
    subs: list[OrderIdFrame | SubaccountFrame | None] = [
      frame['taker'],
      frame['maker'],
      frame['liquidated'],
      frame['offsetting'],
    ]
    return any(s is not None and self.ours(s['owner'], s['number']) for s in subs)


def socket_trade(item: SocketFill, market: PerpetualMarket) -> Trade:
  """An SDK trade from a socket fill; like a node trade, with `details['source'] == 'socket'`."""
  fill = item.fill
  sign = 1 if fill.side == 'BUY' else -1
  return Trade(
    id=fill.id,
    order_id=serialize_id(fill.order_id) if fill.order_id is not None else None,
    price=fill_price(fill, market),
    qty=base_size(fill.quantums, market) * sign,
    time=None,
    maker=fill.maker,
    fee=None,
    details={
      'source': 'socket',
      'height': fill.height,
      'round': item.round,
      'level': item.level,
      'kind': fill.kind,
      'subaccount': fill.subaccount,
    },
  )


def reversal(trade: Trade) -> Trade:
  """The trade undoing a socket trade whose proposal did not commit."""
  return Trade(
    id=f'{trade.id}:revert',
    order_id=trade.order_id,
    price=trade.price,
    qty=-trade.qty,
    time=None,
    maker=trade.maker,
    fee=None,
    details={**(trade.details or {}), 'revert': True},
  )


@dataclass
class ProposedTrades:
  """Trades emitted from proposed socket fills, by `(height, round)`, until a revert
  may void them; kept for `window` blocks."""

  window: int = 50
  trades: dict[tuple[int, int], list[tuple[Trade, FillKey | None]]] = field(
    default_factory=dict[tuple[int, int], list[tuple[Trade, FillKey | None]]]
  )

  def add(self, item: SocketFill, trade: Trade, key: FillKey | None = None):
    """Remember a trade emitted from `item`, with its dedup key if raced."""
    if item.level == 'proposed':
      self.trades.setdefault((item.fill.height, item.round), []).append((trade, key))
      horizon = item.fill.height - self.window
      for k in [k for k in self.trades if k[0] <= horizon]:
        del self.trades[k]

  def pop(self, revert: SocketRevert) -> list[tuple[Trade, FillKey | None]]:
    """The trades a revert voids."""
    return self.trades.pop((revert.height, revert.round), [])


@dataclass
class SocketFeed:
  """Our fills from the daemon's socket, reconnecting forever.

  Each connection subscribes from the last complete height, so the daemon replays what
  was published while disconnected (it retains 300 heights). The feed never fails:
  connection errors are retried with exponential backoff and logged.
  """

  path: str
  address: str
  parent: int

  async def items(self) -> AsyncGenerator[SocketItem, None]:
    """Every fill of ours and every revert, as the daemon publishes them."""
    parser = FrameParser(self.address, self.parent)
    delay = RECONNECT_MIN
    while True:
      try:
        async with unix_connect(
          self.path, 'ws://localhost/', subprotocols=[PROTOCOL], max_size=2**22
        ) as ws:
          await ws.send(
            json.dumps({'tag': 'subscribe', 'from_height': parser.last_block}).encode()
          )
          async for message in ws:
            delay = RECONNECT_MIN
            raw = json.loads(message)
            if raw.get('tag') not in FRAME_TAGS:
              continue
            frame = frame_adapter.validate_python(raw)
            for item in parser.parse(frame):
              yield item
        log.warning('dYdX fill socket closed; reconnecting')
      except asyncio.CancelledError:
        raise
      except Exception as e:
        log.warning('dYdX fill socket failed: %r; retrying in %.1fs', e, delay)
      await asyncio.sleep(delay)
      delay = min(delay * 2, RECONNECT_MAX)


def require_socket(shared: 'Shared') -> str:
  """The account's fill socket path.

  Raises:
    ValueError: When the account does not configure `fill_socket`.
  """
  if shared.fill_socket is None:
    raise ValueError(
      "dYdX trades_source 'socket' needs a fill daemon's socket: set `fill_socket` "
      '(e.g. "/run/dydx-fills.sock") on `accounts.Dydx`.'
    )
  return shared.fill_socket


def socket_fill_subscription(shared: 'Shared') -> Subscription[SocketItem]:
  """The client's one socket feed, fanned out to every market that streams it.

  Raises:
    ValueError: When the account has no `fill_socket`.
  """
  path = require_socket(shared)
  if shared.socket_subscription is None:
    feed = SocketFeed(
      path=path, address=shared.require_address(), parent=shared.parent_subaccount
    )

    async def subscribe():
      """Start the feed; its connection opens on the first read."""
      items = feed.items()
      return items, items.aclose

    shared.socket_subscription = Subscription.of(subscribe)
  return shared.socket_subscription
