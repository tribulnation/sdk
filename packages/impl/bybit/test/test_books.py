"""Folding Bybit's snapshot-then-deltas order book pushes into whole books.

Both cases below corrupt the book silently and permanently: nothing raises, the stream
keeps delivering, and the only symptom is prices that were never on the venue.
"""

from typing_extensions import AsyncIterator, cast
from decimal import Decimal

from tribulnation.bybit.market.impl.mixin import merged_books
from typed_bybit.spot.orderbook import OrderbookUpdate


def update(
  bids: list[tuple[str, str]], asks: list[tuple[str, str]], *, u: int
) -> OrderbookUpdate:
  """One order book push."""
  return cast(
    OrderbookUpdate,
    {
      's': 'BTCUSDT',
      'b': [(Decimal(p), Decimal(q)) for p, q in bids],
      'a': [(Decimal(p), Decimal(q)) for p, q in asks],
      'u': u,
      'seq': u,
    },
  )


async def pushes(*updates: OrderbookUpdate) -> AsyncIterator[OrderbookUpdate]:
  """Replay a fixed sequence of pushes."""
  for u in updates:
    yield u


async def test_a_zero_size_removes_the_level():
  """Bybit withdraws a level by resending it with size zero, not by omitting it.

  A truthiness guard on the size -- the same shape as the `execFee` bug -- reads that
  as "no change" and leaves the level on the book for the life of the connection.
  """
  books = [
    book
    async for book in merged_books(
      pushes(
        update([('100', '1'), ('99', '2')], [], u=7),
        update([('99', '0')], [], u=8),
      )
    )
  ]
  assert [e.price for e in books[1].bids] == [Decimal(100)]


async def test_a_restart_snapshot_replaces_the_book_instead_of_merging():
  """Bybit resends a full snapshot as `u == 1` when the feed restarts.

  Merged rather than replaced, every level the venue dropped during the outage stays
  on the book forever. A live check cannot force a feed restart.
  """
  books = [
    book
    async for book in merged_books(
      pushes(
        update([('100', '1'), ('99', '2')], [], u=7),
        update([('50', '4')], [], u=1),
      )
    )
  ]
  assert [e.price for e in books[1].bids] == [Decimal(50)]
