"""Folding Bitget's `books` channel pushes into whole books.

Every case below corrupts the book silently: nothing raises, the stream keeps
delivering, and the only symptom is prices that were never on the venue.
"""

from typing_extensions import Any, AsyncIterator, Literal, cast
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.bitget.market.impl import merged_books
from typed_bitget.classic_streams.orderbook import OrderBookPush

T = datetime(2026, 9, 8, tzinfo=timezone.utc)


def push(
  action: Literal['snapshot', 'update'],
  bids: list[tuple[str, str]],
  asks: list[tuple[str, str]],
) -> OrderBookPush:
  """One `books` push carrying a single levels entry."""
  frame: dict[str, Any] = {
    'action': action,
    'arg': {'instType': 'SPOT', 'channel': 'books', 'instId': 'BTCUSDT'},
    'data': [
      {
        'bids': [(Decimal(p), Decimal(q)) for p, q in bids],
        'asks': [(Decimal(p), Decimal(q)) for p, q in asks],
        'ts': T,
        'seq': 1,
      }
    ],
    'ts': T,
  }
  return cast(OrderBookPush, frame)


async def pushes(*frames: OrderBookPush) -> AsyncIterator[OrderBookPush]:
  """Replay a fixed sequence of pushes."""
  for frame in frames:
    yield frame


async def test_a_zero_size_removes_the_level():
  """Bitget withdraws a level by resending it with size zero (2 to 10 per live
  update), not by omitting it; a truthiness guard would keep it on the book."""
  books = [
    book
    async for book in merged_books(
      pushes(
        push('snapshot', [('100', '1'), ('99', '2')], [('101', '1')]),
        push('update', [('99', '0')], []),
      )
    )
  ]
  assert [e.price for e in books[1].bids] == [Decimal(100)]
  assert [e.price for e in books[1].asks] == [Decimal(101)]


async def test_an_update_replaces_a_level_and_adds_new_ones():
  """An update carries only the changed levels, each a full replacement."""
  books = [
    book
    async for book in merged_books(
      pushes(
        push('snapshot', [('100', '1')], [('101', '1')]),
        push('update', [('100', '3'), ('98', '5')], [('102', '7')]),
      )
    )
  ]
  assert [(e.price, e.qty) for e in books[1].bids] == [(100, 3), (98, 5)]
  assert [(e.price, e.qty) for e in books[1].asks] == [(101, 1), (102, 7)]


async def test_a_new_snapshot_replaces_the_book_instead_of_merging():
  """A `snapshot` replaces the book; merged, every level the venue dropped while the
  feed was away stays on the book forever."""
  books = [
    book
    async for book in merged_books(
      pushes(
        push('snapshot', [('100', '1'), ('99', '2')], []),
        push('snapshot', [('50', '4')], []),
      )
    )
  ]
  assert [e.price for e in books[1].bids] == [Decimal(50)]


async def test_a_delivered_book_is_never_mutated_by_a_later_push():
  """Each yielded book is a copy, so a subscriber's snapshot stays what it saw."""
  books = [
    book
    async for book in merged_books(
      pushes(
        push('snapshot', [('100', '1')], []),
        push('update', [('100', '0')], []),
      )
    )
  ]
  assert [e.price for e in books[0].bids] == [Decimal(100)]
  assert books[1].bids == []
