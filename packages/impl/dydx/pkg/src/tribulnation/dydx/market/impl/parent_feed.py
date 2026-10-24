"""The parent subaccounts channel, reconnecting and backfilling the fills of each gap
from REST, so no fill of the account is skipped by a dropped connection."""

from typing_extensions import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, cast
from contextlib import suppress
from dataclasses import dataclass, field
import asyncio
import logging

from typed_dydx.indexer.schemas import (
  Fill,
  FillSubaccountMessage,
  OrderSubaccountMessage,
  SubaccountsNotification,
)

from tribulnation.dydx.core import wrap_exceptions
from .orders import indexer_subaccount_id
from .reconnect import Opened, reconnecting

if TYPE_CHECKING:
  from .mixin import Shared

log = logging.getLogger(__name__)

SEEN_HEIGHTS = 100
"""Blocks whose fill ids the feed remembers, to drop backfilled copies."""
BACKFILL_PAGE = 1000
"""Fills per backfill request."""


@dataclass
class ParentFills:
  """The parent subaccounts channel's position in the chain, and the fills it carried.

  After a reconnection, the fills between the last height seen and the new
  subscription's height are fetched from REST. Fills are remembered by id for
  `SEEN_HEIGHTS` blocks, so a fill the channel or the backfill already delivered is
  dropped.
  """

  height: int = 0
  """The highest block height the channel reached."""
  seen: dict[int, set[str]] = field(default_factory=dict[int, set[str]])
  """Ids of the fills delivered, by height."""

  def reached(self, height: int | None):
    """The channel is at `height` (a reply's or a notification's `blockHeight`)."""
    if height is not None and height > self.height:
      self.height = height
      horizon = height - SEEN_HEIGHTS
      for h in [h for h in self.seen if h <= horizon]:
        del self.seen[h]

  def admit(self, msg: SubaccountsNotification) -> SubaccountsNotification:
    """`msg` without the fills already delivered; records the rest and its height."""
    self.reached(msg.get('blockHeight'))
    fills = msg.get('fills')
    if not fills:
      return msg
    new: list[FillSubaccountMessage] = []
    for fill in fills:
      height = fill.get('createdAtHeight') or self.height
      ids = self.seen.setdefault(height, set())
      if fill['id'] not in ids:
        ids.add(fill['id'])
        new.append(fill)
      self.reached(height)
    return {**msg, 'fills': new}


def pushed_fill(
  fill: Fill, *, address: str, clob_pair_ids: dict[str, int]
) -> FillSubaccountMessage:
  """A REST fill as the subaccounts channel would have pushed it.

  `eventId` and `transactionHash` are not in the REST fill and are left empty.
  """
  return {
    'id': fill['id'],
    'subaccountId': indexer_subaccount_id(address, fill['subaccountNumber']),
    'side': fill['side'],
    'liquidity': fill['liquidity'],
    'type': fill['type'],
    'clobPairId': clob_pair_ids[fill['market']],
    'size': fill['size'],
    'price': fill['price'],
    'quoteAmount': fill['price'] * fill['size'],
    'eventId': '',
    'transactionHash': '',
    'createdAt': fill['createdAt'],
    'createdAtHeight': fill['createdAtHeight'],
    'orderId': fill.get('orderId'),
    'ticker': fill['market'],
  }


@wrap_exceptions
async def backfill(
  shared: 'Shared', parent: int, *, after: int, until: int
) -> SubaccountsNotification | None:
  """The parent subaccount's fills at heights `after` to `until` (both included), as a
  channel notification with their orders; `None` when there are none.

  Fills at `after` are included since the channel may have delivered that block only in
  part; `ParentFills` drops those it did.

  Raises:
    NetworkError: A request failed; the gap is not filled (likewise `RateLimited` or
      `ApiError`).
  """
  address = shared.require_address()
  indexer = shared.client.indexer.data
  fills: dict[str, Fill] = {}
  cursor = until
  while True:
    page = (
      await indexer.get_parent_fills(
        address=address,
        parent_subaccount=parent,
        created_before_or_at_height=cursor,
        limit=BACKFILL_PAGE,
      )
    )['fills']
    fills.update((f['id'], f) for f in page if f['createdAtHeight'] >= after)
    lowest = min((f['createdAtHeight'] for f in page), default=after)
    if len(page) < BACKFILL_PAGE or lowest < after:
      break
    if lowest == cursor:
      log.warning(
        'dYdX backfill: over %d fills at height %d; the rest are missed',
        BACKFILL_PAGE,
        cursor,
      )
      break
    cursor = lowest
  if not fills:
    return None
  markets = await shared.load_markets()
  clob_pair_ids = {ticker: int(m['clobPairId']) for ticker, m in markets.items()}
  pushed = [
    pushed_fill(f, address=address, clob_pair_ids=clob_pair_ids)
    for f in sorted(fills.values(), key=lambda f: (f['createdAtHeight'], f['id']))
    if f['market'] in clob_pair_ids
  ]
  order_ids = {order_id for f in pushed if (order_id := f.get('orderId'))}
  orders = await asyncio.gather(*[order_of(shared, id) for id in order_ids])
  return {'blockHeight': until, 'fills': pushed, 'orders': list(orders)}


@wrap_exceptions
async def order_of(shared: 'Shared', order_id: str) -> OrderSubaccountMessage:
  """A backfilled fill's order from REST, which carries the fields the subaccounts
  channel's orders give `stream_order_ids`."""
  return cast(
    OrderSubaccountMessage, await shared.client.indexer.data.get_order(order_id)
  )


def parent_subaccounts_feed(
  shared: 'Shared', parent: int
) -> Callable[[], Awaitable[Opened[SubaccountsNotification]]]:
  """A `Subscription.of` callback for the parent subaccounts channel that reconnects
  (`reconnecting`) and, on each reconnection, emits the fills of the gap first.

  A backfilled notification carries `backfill: True`: its fills are late, which a fill
  race must not count as leads.
  """
  position = ParentFills()

  @wrap_exceptions
  async def open(reopen: bool) -> Opened[SubaccountsNotification]:
    """Subscribe, then backfill from the height reached before the drop."""
    stream = await shared.client.indexer.streams.parent_subaccounts(
      shared.require_address(), subaccount=parent
    )
    try:
      height = stream.reply['blockHeight']
      gap = None
      if reopen and position.height:
        gap = await backfill(shared, parent, after=position.height, until=height)
    except BaseException:
      with suppress(Exception):
        await stream.unsubscribe()
      raise
    position.reached(height)

    @wrap_exceptions
    async def items() -> AsyncIterator[SubaccountsNotification]:
      """The gap's fills, then the channel's notifications, without repeats."""
      if gap is not None:
        late = position.admit(gap)
        if late.get('fills'):
          log.warning(
            'dYdX indexer parent subaccounts: %d fills backfilled from REST',
            len(late.get('fills') or []),
          )
          yield cast(SubaccountsNotification, {**late, 'backfill': True})
      async for msg in stream:
        yield position.admit(msg)

    return items(), stream.unsubscribe

  return reconnecting('parent subaccounts', open)
