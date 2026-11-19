"""Book order: sorted on construction, kept by `update`, the wire and derived books."""

import random
from decimal import Decimal, localcontext

import pytest
from typing_extensions import AsyncIterator

from tribulnation.sdk.gateway import codec
from tribulnation.sdk.market import Book, detached_books
from tribulnation.sdk.market.types.book import reading_books_only


def entry(price: str | int, qty: str | int) -> Book.Entry:
  """A level from short literals."""
  return Book.Entry(Decimal(price), Decimal(qty))


def levels(entries: list[Book.Entry]) -> list[tuple[Decimal, Decimal]]:
  """Levels as plain values, in book order."""
  return [(e.price, e.qty) for e in entries]


def reference_update(book: Book, updates: Book) -> Book:
  """The previous, dict-and-sort `Book.update`, as an oracle for the incremental one."""
  bids = {e.price: e for e in book.bids}
  asks = {e.price: e for e in book.asks}
  for e in updates.bids:
    if e.qty > 0:
      bids[e.price] = e
    else:
      bids.pop(e.price, None)
  for e in updates.asks:
    if e.qty > 0:
      asks[e.price] = e
    else:
      asks.pop(e.price, None)
  sorted_bids = [bids[p] for p in sorted(bids, reverse=True)]
  sorted_asks = [asks[p] for p in sorted(asks)]
  new_bids = {e.price for e in updates.bids if e.qty > 0}
  new_asks = {e.price for e in updates.asks if e.qty > 0}
  i = j = 0
  while (
    i < len(sorted_bids)
    and j < len(sorted_asks)
    and sorted_asks[j].price <= sorted_bids[i].price
  ):
    bid, ask = sorted_bids[i], sorted_asks[j]
    new_bid, new_ask = bid.price in new_bids, ask.price in new_asks
    if new_bid and new_ask:
      if ask.qty >= bid.qty:
        i += 1
      else:
        j += 1
    elif new_bid:
      j += 1
    elif new_ask:
      i += 1
    else:
      break
  return Book(
    bids=sorted_bids[i:],
    asks=sorted_asks[j:],
    time=updates.time if updates.time is not None else book.time,
  )


def test_constructor_sorts_levels():
  """Unsorted input is put in book order; equal prices keep their input order."""
  first, second = entry(5, 1), entry(5, 2)
  book = Book(
    bids=[entry(1, 1), first, entry(9, 1), second],
    asks=[entry(20, 1), entry(10, 1), entry(15, 1)],
  )
  assert [e.price for e in book.bids] == [9, 5, 5, 1]
  assert book.bids[1] is first and book.bids[2] is second
  assert [e.price for e in book.asks] == [10, 15, 20]
  assert Book().bids is not Book().bids


def test_best_levels_are_the_first():
  """`best_bid` and `best_ask` are the first level of each side."""
  book = Book(bids=[entry(1, 1), entry(3, 1)], asks=[entry(7, 1), entry(4, 1)])
  assert book.best_bid is book.bids[0] and book.best_bid.price == 3
  assert book.best_ask is book.asks[0] and book.best_ask.price == 4
  assert book.mark_price == Decimal('3.5')


def test_best_levels_of_empty_sides_raise_value_error():
  """An empty side raises `ValueError`, as the previous `max`/`min` scan did."""
  for book in (Book(), Book(asks=[entry(4, 1)]), Book(bids=[entry(3, 1)])):
    if not book.bids:
      with pytest.raises(ValueError):
        book.best_bid
    if not book.asks:
      with pytest.raises(ValueError):
        book.best_ask


def test_wire_decode_keeps_level_order():
  """Decoded books keep the order on the wire without re-sorting: the protocol sends
  levels in book order, and books the SDK encodes round-trip unchanged."""
  book = Book(bids=[entry(3, 1), entry(2, 1)], asks=[entry(4, 1), entry(5, 1)])
  resp = codec.decode_server(codec.encode_server(codec.DepthResp(id='1', book=book)))
  assert isinstance(resp, codec.DepthResp) and resp.book == book
  frame = (
    b'{"id":"1","tag":"depth","book":{"bids":[{"price":"2","qty":"1"},'
    b'{"price":"3","qty":"1"}],"asks":[]}}'
  )
  resp = codec.decode_server(frame)
  assert isinstance(resp, codec.DepthResp)
  assert [e.price for e in resp.book.bids] == [2, 3]


def test_limit_keeps_order_and_shares_entries():
  """`limit` slices new lists in order; its entries are the book's own."""
  book = Book(bids=[entry(3, 1), entry(2, 1)], asks=[entry(4, 1), entry(5, 1)])
  top = book.limit(1)
  assert levels(top.bids) == [(3, 1)] and levels(top.asks) == [(4, 1)]
  assert top.bids[0] is book.bids[0] and top.bids is not book.bids


def test_copy_is_independent():
  """Mutating a copy's lists or entries, or filling against it, leaves the original."""
  book = Book(bids=[entry(3, 1), entry(2, 1)], asks=[entry(4, 1), entry(5, 1)])
  seen = levels(book.bids), levels(book.asks)
  mine = book.copy()
  mine.bids[0].qty = Decimal(9)
  mine.asks.pop()
  assert mine.buy(qty=Decimal('0.5')) == 4
  assert (levels(book.bids), levels(book.asks)) == seen


def test_update_replaces_adds_and_removes_levels():
  """A Lighter-style delta sequence: replace, add inside and outside, remove the best
  level, remove an absent level, then empty a side."""
  book = Book(
    bids=[entry(100, 1), entry(99, 2), entry(97, 3)],
    asks=[entry(101, 1), entry(102, 2), entry(104, 3)],
  )
  book.update(Book(bids=[entry(99, 5), entry(98, 1)], asks=[entry(103, 1)]))
  assert levels(book.bids) == [(100, 1), (99, 5), (98, 1), (97, 3)]
  assert levels(book.asks) == [(101, 1), (102, 2), (103, 1), (104, 3)]
  book.update(Book(bids=[entry(100, 0), entry(50, 1)], asks=[entry(105, 0)]))
  assert levels(book.bids) == [(99, 5), (98, 1), (97, 3), (50, 1)]
  assert levels(book.asks) == [(101, 1), (102, 2), (103, 1), (104, 3)]
  book.update(Book(bids=[entry(101, 0), entry('100.5', 2)], asks=[entry(100, 0)]))
  assert levels(book.bids)[0] == (Decimal('100.5'), 2)
  book.update(Book(asks=[entry(101, 0), entry(102, 0), entry(103, 0), entry(104, 0)]))
  assert book.asks == [] and len(book.bids) == 5
  book.update(Book(asks=[entry(106, 1)]))
  assert levels(book.asks) == [(106, 1)]


def test_update_collapses_only_touched_repeated_prices():
  """A changed price replaces all its repeated levels; untouched repeats remain."""
  book = Book(bids=[entry(5, 1), entry(5, 2), entry(4, 1), entry(4, 2)])
  book.update(Book(bids=[entry(5, 7)]))
  assert levels(book.bids) == [(5, 7), (4, 1), (4, 2)]
  book.update(Book(bids=[entry(4, 0)]))
  assert levels(book.bids) == [(5, 7)]


def test_update_last_repeat_in_a_delta_wins():
  """Repeated prices within one delta apply in order, the last one winning."""
  book = Book(bids=[entry(5, 1)])
  book.update(Book(bids=[entry(6, 1), entry(6, 0), entry(5, 3), entry(5, 4)]))
  assert levels(book.bids) == [(5, 4)]


def test_update_ignores_the_decimal_context():
  """Bid levels are located exactly, even under a low-precision decimal context."""
  book = Book(bids=[entry('12345.5', 1), entry('12345.4', 1)])
  with localcontext() as context:
    context.prec = 4
    book.update(Book(bids=[entry('12345.4', 0)]))
  assert levels(book.bids) == [(Decimal('12345.5'), 1)]


@pytest.mark.parametrize('seed', range(5))
def test_update_matches_the_reference(seed: int):
  """Random deltas over a deep book, with removals, crossings and repeated prices,
  leave the same book as the previous implementation, entry for entry."""
  rng = random.Random(seed)
  book = Book(
    bids=[entry(1000 - i, i + 1) for i in range(60)],
    asks=[entry(1001 + i, i + 1) for i in range(60)],
  )
  expected = book.frozen()
  for _ in range(500):

    def side(lo: int, hi: int) -> list[Book.Entry]:
      return [
        entry(rng.randint(lo, hi), rng.choice([0, 0, 1, 2, 5]))
        for _ in range(rng.randint(0, 6))
      ]

    mid = 1000 + rng.randint(-3, 3)
    delta = Book(bids=side(mid - 70, mid + 2), asks=side(mid - 1, mid + 70))
    expected = reference_update(expected, delta)
    book.update(delta)
    assert levels(book.bids) == levels(expected.bids)
    assert levels(book.asks) == levels(expected.asks)
    assert all(
      a is b for a, b in zip(book.bids + book.asks, expected.bids + expected.asks)
    )


async def shared_books(*books: Book) -> AsyncIterator[Book]:
  """Replay shared books."""
  for book in books:
    yield book


async def test_detached_books_copy_unless_reading_only():
  """Subscribers get copies; a read-only reader gets the shared books, trimmed."""
  shared = Book(bids=[entry(3, 1), entry(2, 1)], asks=[entry(4, 1), entry(5, 1)])
  copied = [b async for b in detached_books(shared_books(shared))]
  assert copied == [shared] and copied[0].bids[0] is not shared.bids[0]
  token = reading_books_only.set(True)
  try:
    whole = [b async for b in detached_books(shared_books(shared))]
    top = [b async for b in detached_books(shared_books(shared), 1)]
  finally:
    reading_books_only.reset(token)
  assert whole[0] is shared
  assert levels(top[0].bids) == [(3, 1)] and top[0].bids[0] is shared.bids[0]
