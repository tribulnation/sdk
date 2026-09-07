"""Coinbase's two Advanced Trade WebSocket channels, reshaped into SDK streams.

Both channels are incremental: `level2` sends one snapshot then deltas, and `user` sends
order-level cumulative quantities rather than itemized fills. A `Subscription` fans one
upstream out to many subscribers, and a subscriber that joins late never sees the frames
that came before it -- so the incremental state is folded *here*, once per connection,
and what the fan-out carries is already self-contained: a whole `Book` per update, and
one `Trade` per quantity increase.
"""

from typing_extensions import Any, AsyncIterable, Awaitable, Callable
from decimal import Decimal

from tribulnation.sdk.market import Book, Trade

from typed_coinbase import Coinbase

from .exc import wrap_exceptions

Unsubscribe = Callable[[], Awaitable[Any]]


@wrap_exceptions
async def book_stream(
  client: Coinbase, product_id: str
) -> tuple[AsyncIterable[Book], Unsubscribe]:
  """Subscribe to a product's `level2` channel, yielding a whole book per update.

  Args:
    client: The Coinbase client owning the market-data connection.
    product_id: Product to subscribe to, e.g. `BTC-USD`.
  """
  stream = await client.app.advanced_trade.streams.market_data.level2([product_id])

  @wrap_exceptions
  async def books() -> AsyncIterable[Book]:
    book = Book()
    async for message in stream:
      for event in message['events']:
        if event['product_id'] != product_id:
          continue
        update = Book(
          bids=[
            Book.Entry(price=u['price_level'], qty=u['new_quantity'])
            for u in event['updates']
            if u['side'] == 'bid'
          ],
          # Verified live: the ask side of a `level2` update reads `offer`, not `ask`.
          asks=[
            Book.Entry(price=u['price_level'], qty=u['new_quantity'])
            for u in event['updates']
            if u['side'] == 'offer'
          ],
        )
        if event['type'] == 'snapshot':
          book = update
        else:
          book.update(update)
        yield book.copy()

  return books(), stream.unsubscribe


@wrap_exceptions
async def user_trades_stream(
  client: Coinbase,
) -> tuple[AsyncIterable[tuple[str, Trade]], Unsubscribe]:
  """Subscribe to the `user` channel, yielding `(product_id, trade)` per fill.

  Best-effort: the channel carries order-level `cumulative_quantity` snapshots, not
  itemized per-fill events, so each increase is reconstructed as one `Trade` and
  per-fill maker/taker and fee are lost. `Market.trades_history` is the reliable
  source for those. The first frame observed for an order is treated as one trade of
  its whole cumulative quantity, since nothing on the channel says how much of it
  predates the subscription.

  Args:
    client: The Coinbase client owning the user connection.
  """
  stream = await client.app.advanced_trade.streams.user.orders()

  @wrap_exceptions
  async def trades() -> AsyncIterable[tuple[str, Trade]]:
    filled: dict[str, Decimal] = {}
    async for message in stream:
      for event in message['events']:
        for order in event['orders']:
          cumulative_quantity = order.get('cumulative_quantity')
          if not cumulative_quantity:
            continue
          previous = filled.get(order['order_id'], Decimal(0))
          if cumulative_quantity <= previous:
            continue
          filled[order['order_id']] = cumulative_quantity
          sign = 1 if order['order_side'] == 'BUY' else -1
          yield (
            order['product_id'],
            Trade(
              id=f'{order["order_id"]}:{cumulative_quantity}',
              price=order.get('avg_price') or Decimal(0),
              qty=sign * (cumulative_quantity - previous),
              time=message['timestamp'],
              maker=False,
              details=order,
            ),
          )

  return trades(), stream.unsubscribe
