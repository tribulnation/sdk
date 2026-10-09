from typing_extensions import (
  AsyncContextManager,
  AsyncIterable,
  Awaitable,
  Iterator,
  Sequence,
)
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
import asyncio

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
from .dedup import FillDedup
from .mixin import MarketMixin, ParentSubaccountNotification, settings_adapter
from .node_fills import FillKey, NodeFill, node_key, node_trade
from .node_stream import node_fill_subscription
from .orders import stream_order_ids


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
  `trades_source` the dYdX settings select (see `Settings.trades_source`).

  Raises:
    ValueError: On entry, for `'node'` or `'fastest'` without the account's full node
      endpoints.
  """
  source = settings_adapter.validate_python(settings.get('dydx', {})).get(
    'trades_source', 'indexer'
  )
  match source:
    case 'indexer':
      return indexer_stream(self, queue_size=queue_size, overflow=overflow)
    case 'node':
      return node_stream(self, queue_size=queue_size, overflow=overflow)
    case 'fastest':
      return fastest_stream(self, queue_size=queue_size, overflow=overflow)


@asynccontextmanager
@wrap_exceptions
async def indexer_stream(
  self: MarketMixin, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
):
  """The market's fills from the indexer's parent subaccounts channel."""
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
@wrap_exceptions
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
@wrap_exceptions
async def fastest_stream(
  self: MarketMixin, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
):
  """The market's fills from the full node and the indexer, each emitted once, by the
  first source to deliver it (`FillDedup`).

  Node trades carry `details['source'] == 'node'`; indexer trades carry
  `{'source': 'indexer', 'fill': <indexer fill>}`. The node feed never fails, so an
  indexer failure (or this subscriber overflowing) ends the stream with that error.
  """
  subscription = node_fill_subscription(self.shared)
  parent = self.shared.parent_subaccount
  address = self.address
  clob_pair_id = int(self.perpetual_market['clobPairId'])
  out = StreamInbox[Trade].new(queue_size, overflow)
  dedup = FillDedup()

  async def from_indexer(logs: AsyncIterable[ParentSubaccountNotification]):
    """Admit the indexer's fills."""
    async for log in logs:
      for trade, fill in indexer_trades(
        log, market=self.market, address=address, parent=parent
      ):
        if dedup.admit('indexer', indexer_key(fill)):
          trade.details = {'source': 'indexer', 'fill': fill}
          if not out.push(trade):
            return

  async def from_node(fills: AsyncIterable[NodeFill]):
    """Admit the node's fills."""
    async for fill in fills:
      if fill.clob_pair_id != clob_pair_id:
        continue
      key = node_key(fill, self.perpetual_market, address=address)
      if dedup.admit('node', key) and not out.push(
        node_trade(fill, self.perpetual_market)
      ):
        return

  async def pump(source: Awaitable[None]):
    """Run one source; its end or failure ends the merged stream."""
    try:
      await source
      out.fail(NetworkError('dYdX trades source ended unexpectedly'))
    except asyncio.CancelledError:
      raise
    except Exception as e:
      out.fail(translate(e) if isinstance(e, VenueError) else e)

  async with (
    self.subscribe_parent_subaccount(parent, queue_size=queue_size) as logs,
    subscription.subscribe(queue_size=queue_size) as fills,
    managed_tasks([pump(from_indexer(logs)), pump(from_node(fills))]),
  ):
    yield out
