"""Candles, personal fills and the fills stream."""

from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta

from typing_extensions import AsyncIterable, AsyncIterator, Literal, Sequence
from typed_evedex.exchange.fills import AccountFill
from typed_evedex.streams.account.fills import OrderFillUpdate
from tribulnation.sdk.core import OverflowPolicy, Subscription
from tribulnation.sdk.market import Candle, CandleInterval, ExchangeTrade, Trade

from ..core import FILLS, Shared, wrap_exceptions
from .common import fill_fee, parse_fill, parse_stream_fill

CANDLE_INTERVALS = frozenset[CandleInterval](['1m', '5m', '15m', '1h', '4h', '1d'])
"""Every contract interval; the venue's `group` takes each under the same name."""
FILLS_PAGE = 100
"""Fills per history page."""
EPSILON = timedelta(milliseconds=1)
"""The venue's time resolution: `after` is exclusive, so a bound one step earlier keeps a
fill stamped exactly at `start`."""


async def candles(
  shared: Shared,
  instrument: str,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterable[Sequence[Candle]]:
  """Trade candles opening in `[start, end)`, newest page first and oldest first within
  a page, from the venue's backwards walk; volume in the base asset and the quote coin.

  A row is `[openTime, open, close, high, low, volumeUsd, volume]`.
  """
  if start >= end:
    return
  pages = shared.client.market_data.candles_paged(
    instrument=instrument, after=start, before=end, group=interval
  ).via(shared.call)
  async for page in pages:
    rows = [
      Candle(
        time=t,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=volume,
        quote_volume=quote_volume,
      )
      for t, o, c, h, lo, quote_volume, volume in page
      if start <= t < end
    ]
    if rows:
      yield rows


async def fill_sides(
  shared: Shared, fills: Sequence[AccountFill]
) -> dict[str, Literal['BUY', 'SELL']]:
  """The side of each fill's order, from one `orders.list` read of the page's orders."""
  ids = sorted({f['order'] for f in fills})
  sides: dict[str, Literal['BUY', 'SELL']] = {}
  pages = shared.client.exchange.orders.list_paged(id=ids, limit=len(ids)).via(
    shared.call
  )
  async for page in pages:
    sides.update((o['id'], o['side']) for o in page)
  return sides


async def fill_fees(shared: Shared, order_ids: Sequence[str]) -> dict[str, Trade.Fee]:
  """The fee of every fill of the given orders, by fill id (`orders.fills`, one read
  per order: account fills carry no fee)."""
  fees: dict[str, Trade.Fee] = {}
  for order in order_ids:
    rows = await shared.call(lambda: shared.client.exchange.orders.fills(order))
    for row in rows:
      if (fee := fill_fee(row['fee'])) is not None:
        fees[row['id']] = fee
  return fees


async def trades_history(
  shared: Shared, instrument: str | None, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """The account's fills with `start <= time <= end`, in the venue's order (newest
  first); exchange-wide rows are `ExchangeTrade`s.

  Fills carry neither side nor fee: each page reads its orders' sides in one request
  and their fills' fees with one request per order.
  """
  shared.require_account()
  pages = shared.client.exchange.fills_paged(
    instrument, after=start - EPSILON, before=end, limit=FILLS_PAGE
  ).via(shared.call)
  async for page in pages:
    fills = [f for f in page if start <= f['createdAt'] <= end]
    if not fills:
      continue
    sides = await fill_sides(shared, fills)
    fees = await fill_fees(shared, sorted(sides))
    rows: list[Trade] = []
    for f in fills:
      side = sides.get(f['order'])
      if side is None:
        raise ValueError(f'EVEDEX fill {f["id"]}: order {f["order"]} not found')
      trade = parse_fill(f, side=side, fee=fees.get(f['id']))
      rows.append(
        trade
        if instrument is not None
        else ExchangeTrade(**vars(trade), market_id=f['instrument'])
      )
    yield rows


def fills_subscription(shared: Shared) -> Subscription[OrderFillUpdate]:
  """The account's one `orderFills` upstream, every instrument: markets share it and
  filter."""
  if FILLS not in shared.fills:

    @wrap_exceptions
    async def connect() -> Subscription.Context[OrderFillUpdate]:
      """Subscribe; the client authorizes the channel with the wallet's session."""
      manager = shared.client.streams.account.fills()
      stack = AsyncExitStack()
      stream = await stack.enter_async_context(manager)

      @wrap_exceptions
      async def frames() -> AsyncIterator[OrderFillUpdate]:
        """Every fill of the account."""
        async for frame in stream:
          yield frame

      @wrap_exceptions
      async def close():
        """Unsubscribe."""
        await stack.aclose()

      return Subscription.Context(frames(), close)

    shared.fills[FILLS] = Subscription(connect)
  return shared.fills[FILLS]


@asynccontextmanager
async def trades_stream(
  shared: Shared,
  instrument: str,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
):
  """Fan out the account's new fills, filtered to one instrument; the channel carries
  no fee. The bounded queue holds every instrument's fills, since they share one
  upstream.

  Raises:
    AuthError: The client has no wallet key.
  """
  shared.require_wallet()
  await shared.instrument(instrument)
  source = fills_subscription(shared)

  async def fills(stream: AsyncIterable[OrderFillUpdate]) -> AsyncIterator[Trade]:
    """The instrument's fills, as `Trade`s."""
    async for frame in stream:
      if frame['instrument'] == instrument:
        yield parse_stream_fill(frame)

  async with source.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield fills(stream)
