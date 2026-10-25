from typing_extensions import (
  AsyncContextManager,
  AsyncIterable,
  Awaitable,
  Iterator,
  Sequence,
  cast,
)
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime
from decimal import Decimal
import asyncio
import logging

from typed_dydx.indexer.schemas import FillSubaccountMessage
from tribulnation.sdk.market import Settings, Trade
from tribulnation.sdk.core import (
  NetworkError,
  OverflowPolicy,
  PaginatedResponse,
  StreamInbox,
  managed_tasks,
)

from tribulnation.dydx.core import wrap_exceptions
from tribulnation.dydx.core.exceptions import VenueError, translate
from .dedup import FillDedup, FillRace
from .mixin import (
  INDEXER_RECONNECT_WINDOW,
  MarketMixin,
  ParentFeedItem,
  ParentSubaccountNotification,
  settings_adapter,
)
from .node_fills import FillKey, NodeFill, node_key, node_trade
from .node_stream import node_fill_subscription
from .orders import stream_order_ids
from .reconnect import Dropped, Reconnected
from .socket_fills import (
  ProposedTrades,
  SocketItem,
  SocketRevert,
  reversal,
  socket_fill_subscription,
  socket_trade,
)

log = logging.getLogger(__name__)


@PaginatedResponse.lift
@wrap_exceptions
async def trades_history(
  self: MarketMixin, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """The market's fills across every address subaccount.

  Fills name their order by its indexer id alone, a hash of the protocol order id, so
  `order_id` is `None`.
  """
  start = start.astimezone()
  end = end.astimezone()

  def within(time: datetime) -> bool:
    return start <= time <= end

  address = self.address
  subaccounts = (
    await self.call_dydx(lambda: self.indexer.data.get_subaccounts(address))
  )['subaccounts']

  for sub in subaccounts:
    paging = self.indexer.data.get_fills_paged(
      address=address,
      subaccount=int(sub['subaccountNumber']),
      created_before_or_at=end,
      market=self.market,
      market_type='PERPETUAL',
    )
    async for fills in paging.via(self.call_dydx):
      trades: list[Trade] = []
      for fill in fills:
        if fill['market'] != self.market or not within(fill['createdAt']):
          continue
        sign = 1 if fill['side'] == 'BUY' else -1
        trades.append(
          Trade(
            id=fill['id'],
            price=Decimal(fill['price']),
            qty=Decimal(fill['size']) * sign,
            time=fill['createdAt'],
            maker=fill['liquidity'] == 'MAKER',
            fee=Trade.Fee(asset='USDC', amount=Decimal(fill['fee'])),
            details=fill,
          )
        )
      if trades:
        yield trades


def indexer_trades(
  log: ParentSubaccountNotification, *, market: str, address: str, parent: int
) -> Iterator[tuple[Trade, FillSubaccountMessage]]:
  """A market's fills in a parent subaccounts message, with the fill each came from.

  The indexer pushes an order's fill together with the order, which gives its
  `order_id`. Fills without an order of the account's (the liquidated or deleveraged
  side) have none.
  """
  fills = log.get('fills')
  if fills is None:
    return
  order_ids = stream_order_ids(log.get('orders') or [], address=address, parent=parent)
  for fill in fills:
    if fill['ticker'] != market:
      continue
    sign = 1 if fill['side'] == 'BUY' else -1
    order_id = fill.get('orderId')
    trade = Trade(
      id=fill['id'],
      order_id=order_ids.get(order_id) if order_id else None,
      price=Decimal(fill['price']),
      qty=Decimal(fill['size']) * sign,
      time=fill['createdAt'],
      maker=fill['liquidity'] == 'MAKER',
      fee=None,
      details=fill,
    )
    yield trade, fill


def indexer_key(fill: FillSubaccountMessage) -> FillKey | None:
  """The dedup key of an indexer fill; `None` without `createdAtHeight`."""
  height = fill.get('createdAtHeight')
  if height is None:
    return None
  order_id = fill.get('orderId')
  if order_id:
    return FillKey(height, f'order:{order_id}', Decimal(fill['size']))
  return FillKey(
    height,
    f'orderless:{fill["subaccountId"]}:{fill["clobPairId"]}:{fill["side"]}',
    Decimal(fill['size']),
  )


def trades_stream(
  self: MarketMixin,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
  settings: Settings = {},
) -> AsyncContextManager[AsyncIterable[Trade]]:
  """The market's fills across the parent subaccount and its children, from the
  `trades_source` the dYdX settings select, else the account's `fill_source`, else the
  indexer (see `Settings.trades_source`).

  Raises:
    ValueError: On entry, for `'node'` without the account's full node endpoints,
      `'socket'` without its `fill_socket`, or `'fastest'` with neither.
  """
  dydx = settings_adapter.validate_python(settings.get('dydx', {}))
  source = dydx.get('trades_source', self.shared.fill_source or 'indexer')
  match source:
    case 'indexer':
      return indexer_stream(self, queue_size=queue_size, overflow=overflow)
    case 'node':
      return node_stream(self, queue_size=queue_size, overflow=overflow)
    case 'socket':
      return socket_stream(self, queue_size=queue_size, overflow=overflow)
    case 'fastest':
      return fastest_stream(
        self,
        queue_size=queue_size,
        overflow=overflow,
        reconnect_window=dydx.get('indexer_reconnect_window', INDEXER_RECONNECT_WINDOW),
      )


@asynccontextmanager
async def indexer_stream(
  self: MarketMixin, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
):
  """The market's fills from the indexer's parent subaccounts channel; a dropped
  connection ends them with `NetworkError`.

  Not wrapped in `wrap_exceptions` itself: wrapping a context manager's generator
  re-yields from an inner generator that the context's exit never reaches, so its
  subscription would only be released when garbage collected. The subscription and the
  stream translate their own errors.
  """
  parent = self.shared.parent_subaccount
  async with self.subscribe_parent_subaccount(
    parent,
    queue_size=queue_size,
    overflow=overflow,
  ) as parent_subaccounts:

    @wrap_exceptions
    async def gen() -> AsyncIterable[Trade]:
      address = self.address
      async for log in parent_subaccounts:
        for trade, _ in indexer_trades(
          log, market=self.market, address=address, parent=parent
        ):
          yield trade

    yield gen()


@asynccontextmanager
async def node_stream(
  self: MarketMixin, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
):
  """The market's fills from the account's full node."""
  subscription = node_fill_subscription(self.shared)
  clob_pair_id = int(self.perpetual_market['clobPairId'])
  async with subscription.subscribe(queue_size=queue_size, overflow=overflow) as fills:

    async def gen() -> AsyncIterable[Trade]:
      async for fill in fills:
        if fill.clob_pair_id == clob_pair_id:
          yield node_trade(fill, self.perpetual_market)

    yield gen()


@asynccontextmanager
async def socket_stream(
  self: MarketMixin, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
):
  """The market's fills from the account's fill socket, with a reversing trade
  for each proposed fill whose proposal did not commit."""
  subscription = socket_fill_subscription(self.shared)
  clob_pair_id = int(self.perpetual_market['clobPairId'])
  async with subscription.subscribe(queue_size=queue_size, overflow=overflow) as items:

    async def gen() -> AsyncIterable[Trade]:
      proposed = ProposedTrades()
      async for item in items:
        if isinstance(item, SocketRevert):
          for trade, _ in proposed.pop(item):
            yield reversal(trade)
        elif item.fill.clob_pair_id == clob_pair_id:
          trade = socket_trade(item, self.perpetual_market)
          proposed.add(item, trade)
          yield trade

    yield gen()


@asynccontextmanager
async def fastest_stream(
  self: MarketMixin,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
  reconnect_window: float = INDEXER_RECONNECT_WINDOW,
):
  """The market's fills from every configured source, each emitted once, by the first
  source to deliver it (`FillDedup`).

  The sources are the indexer, plus the full node and the fill socket when the
  account configures them. Trades carry `details['source']` (`'node'`, `'socket'`, or
  `'indexer'` with `details['fill']`, the indexer fill). The indexer is the floor, but
  its channel reconnects on a dropped connection and backfills the gap
  (`parent_subaccounts_feed`), the other sources racing on meanwhile; an indexer down
  for over `reconnect_window` seconds (`0`: at once), or this subscriber overflowing,
  ends the stream with an error. A node or socket source that ends or fails (e.g. a node behind the
  chain tip as it connects, `NodeFeed`) is dropped with a warning and the others race
  on. Each later copy of a fill logs (INFO) which source was first and by how many
  milliseconds; the client's `fill_race` keeps the totals and logs them every
  `RACE_LOG_INTERVAL` seconds. Several streams of one market log each fill once
  (`FillRace.racing`).

  Raises:
    ValueError: On entry, when the account configures neither a full node nor a socket.
  """
  shared = self.shared
  if shared.full_node is None and shared.fill_socket is None:
    raise ValueError(
      "dYdX trades_source 'fastest' races the indexer against a full node or a "
      'fill socket: set `full_node_grpc` and `full_node_rpc`, or `fill_socket`, '
      'on `accounts.Dydx`.'
    )
  parent = shared.parent_subaccount
  address = self.address
  market = self.perpetual_market
  clob_pair_id = int(market['clobPairId'])
  out = StreamInbox[Trade].new(queue_size, overflow)
  if shared.fill_race is None:
    shared.fill_race = FillRace()
  race = shared.fill_race
  dedup = FillDedup(race=race)
  loop = asyncio.get_running_loop()

  async def from_indexer(feed: AsyncIterable[ParentFeedItem]):
    """Admit the indexer's fills; fail once its channel is down for over
    `reconnect_window` seconds."""
    items = aiter(feed)
    deadline: float | None = None
    while True:
      timeout = None if deadline is None else max(deadline - loop.time(), 0)
      try:
        notification = await asyncio.wait_for(anext(items), timeout)
      except StopAsyncIteration:
        return
      except asyncio.TimeoutError:
        raise NetworkError(
          f'dYdX indexer down for over {reconnect_window:g}s (indexer_reconnect_window)'
        ) from None
      if isinstance(notification, Dropped):
        if reconnect_window <= 0:
          raise NetworkError(str(notification.error)) from notification.error
        deadline = loop.time() + reconnect_window
        continue
      if isinstance(notification, Reconnected):
        deadline = None
        continue
      late = cast(dict[str, object], notification).get('backfill') is True
      for trade, fill in indexer_trades(
        notification, market=self.market, address=address, parent=parent
      ):
        if dedup.admit('indexer', indexer_key(fill), at=loop.time(), late=late):
          trade.details = {'source': 'indexer', 'fill': fill}
          if not out.push(trade):
            return

  async def from_node(fills: AsyncIterable[NodeFill]):
    """Admit the node's fills."""
    async for fill in fills:
      if fill.clob_pair_id != clob_pair_id:
        continue
      key = node_key(fill, market, address=address)
      if dedup.admit('node', key, at=loop.time()) and not out.push(
        node_trade(fill, market)
      ):
        return

  async def from_socket(items: AsyncIterable[SocketItem]):
    """Admit the socket's fills; retract and reverse those of a proposal that did not
    commit."""
    proposed = ProposedTrades()
    async for item in items:
      if isinstance(item, SocketRevert):
        for trade, key in proposed.pop(item):
          if key is not None:
            dedup.retract('socket', key)
          if not out.push(reversal(trade)):
            return
      elif item.fill.clob_pair_id == clob_pair_id:
        key = node_key(item.fill, market, address=address)
        if dedup.admit('socket', key, at=loop.time()):
          trade = socket_trade(item, market)
          proposed.add(item, trade, key)
          if not out.push(trade):
            return

  async def floor(source: Awaitable[None]):
    """Run the indexer; its end or lasting failure ends the merged stream."""
    try:
      await source
      out.fail(NetworkError('dYdX indexer fills ended unexpectedly'))
    except asyncio.CancelledError:
      raise
    except Exception as e:
      out.fail(translate(e) if isinstance(e, VenueError) else e)

  async def optional(name: str, source: Awaitable[None]):
    """Run a node or socket source; its end or failure only drops it."""
    try:
      await source
      log.warning('dYdX %s fills ended; racing without them', name)
    except asyncio.CancelledError:
      raise
    except Exception as e:
      log.warning('dYdX %s fills failed: %r; racing without them', name, e)

  async with AsyncExitStack() as stack:
    dedup.recording = stack.enter_context(race.racing(clob_pair_id))
    logs = await stack.enter_async_context(
      self.subscribe_parent_feed(parent, queue_size=queue_size)
    )
    tasks: list[Awaitable[None]] = [floor(from_indexer(logs))]
    if shared.full_node is not None:
      fills = await stack.enter_async_context(
        node_fill_subscription(shared).subscribe(queue_size=queue_size)
      )
      tasks.append(optional('full node', from_node(fills)))
    if shared.fill_socket is not None:
      items = await stack.enter_async_context(
        socket_fill_subscription(shared).subscribe(queue_size=queue_size)
      )
      tasks.append(optional('fill socket', from_socket(items)))
    await stack.enter_async_context(managed_tasks(tasks))
    yield out
