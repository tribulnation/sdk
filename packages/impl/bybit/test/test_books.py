"""Folding Bybit's snapshot-then-deltas order book pushes into whole books.

Every case below corrupts the book silently and permanently: nothing raises, the
stream keeps delivering, and the only symptom is prices that were never on the venue.
"""

from typing_extensions import AsyncIterator, Literal, cast
from decimal import Decimal

from tribulnation.bybit.market.impl.mixin import merged_books
from typed_bybit.spot.orderbook import OrderbookUpdate


def update(
  bids: list[tuple[str, str]],
  asks: list[tuple[str, str]],
  *,
  u: int,
  kind: Literal['snapshot', 'delta'] | None = None,
) -> OrderbookUpdate:
  """One order book push; `kind` omitted is a push carrying no frame `type`."""
  frame: dict[str, object] = {
    's': 'BTCUSDT',
    'b': [(Decimal(p), Decimal(q)) for p, q in bids],
    'a': [(Decimal(p), Decimal(q)) for p, q in asks],
    'u': u,
    'seq': u,
  }
  if kind is not None:
    frame['type'] = kind
  return cast(OrderbookUpdate, frame)


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
  """A push typed `snapshot` replaces the book, whatever its update id.

  Merged rather than replaced, every level the venue dropped during the outage stays
  on the book forever. A live check cannot force a feed restart.
  """
  books = [
    book
    async for book in merged_books(
      pushes(
        update([('100', '1'), ('99', '2')], [], u=7, kind='delta'),
        update([('50', '4')], [], u=8, kind='snapshot'),
      )
    )
  ]
  assert [e.price for e in books[1].bids] == [Decimal(50)]


async def test_a_push_without_a_type_falls_back_to_the_update_id():
  """The frame's `type` is declared `NotRequired`, so `u == 1` still has to work.

  The client's core merges `type` in from the frame, which its own example replay
  cannot see, so the field is optional in the declaration even though every live push
  carries it. A push arriving without one must still be recognised as a re-snapshot.
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
