"""Book streams share one maintained book without copying it per update.

A stream takes `Book.frozen` after each update and every subscriber reads
`detached_books`. Consumers must still never see a book mutated under them: neither by
a later update nor by another subscriber mutating its own book.
"""

import asyncio
import copy
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from typing_extensions import AsyncIterator

from tribulnation.sdk.core import StreamInbox, Subscription, skipped
from tribulnation.sdk.market import Book, detached_books

T = datetime(2026, 10, 23, tzinfo=timezone.utc)


def levels(book: Book) -> tuple[list[tuple[Decimal, Decimal]], ...]:
  """A book's levels as plain values, for comparison across copies."""
  return [(e.price, e.qty) for e in book.bids], [(e.price, e.qty) for e in book.asks]


def deep_book(depth: int = 50) -> Book:
  """A book `depth` levels a side around 1000."""
  return Book(
    bids=[Book.Entry(Decimal(1000 - i), Decimal(i + 1)) for i in range(depth)],
    asks=[Book.Entry(Decimal(1001 + i), Decimal(i + 1)) for i in range(depth)],
    time=T,
  )


def deltas(n: int, *, depth: int = 50, seed: int = 0) -> list[Book]:
  """`n` random deltas over the price range of `deep_book`: changes, adds, removals."""
  rng = random.Random(seed)

  def side(lo: int, hi: int) -> list[Book.Entry]:
    return [
      Book.Entry(Decimal(rng.randint(lo, hi)), Decimal(rng.choice([0, 1, 2, 5])))
      for _ in range(rng.randint(1, 4))
    ]

  return [
    Book(
      bids=side(1000 - depth - 5, 1000),
      asks=side(1001, 1001 + depth + 5),
      time=T + timedelta(seconds=i + 1),
    )
    for i in range(n)
  ]


def test_copy_is_independent_and_keeps_order():
  """`copy` matches `deepcopy`: same levels and order, no shared lists or entries."""
  book = deep_book()
  book.bids.reverse()  # copies keep the order as is, without re-sorting
  seen = levels(book)
  mine = book.copy()
  assert levels(mine) == levels(copy.deepcopy(book)) == seen and mine.time == T
  mine.bids[0].qty = Decimal(99)
  mine.asks.pop()
  assert mine.buy(qty=Decimal(1)) is not None
  assert levels(book) == seen


def test_frozen_is_unaffected_by_later_updates():
  """A frozen book keeps its levels through any later update of the live book."""
  book = deep_book()
  frames: list[tuple[Book, tuple[list[tuple[Decimal, Decimal]], ...]]] = []
  for delta in deltas(200):
    book.update(delta)
    frozen = book.frozen()
    frames.append((frozen, levels(frozen)))
  for frozen, seen in frames:
    assert levels(frozen) == seen


def test_update_never_mutates_an_entry():
  """The invariant `frozen` relies on: `update` rebinds lists, never edits entries."""
  book = deep_book()
  entries = {id(e): (e, e.price, e.qty) for e in book.bids + book.asks}
  bids, asks = book.bids, book.asks
  before = list(bids), list(asks)
  for delta in deltas(200):
    book.update(delta)
  assert all(e.price == p and e.qty == q for e, p, q in entries.values())
  assert (bids, asks) == before


async def stream(*books: Book) -> AsyncIterator[Book]:
  """Replay a fixed sequence of books."""
  for book in books:
    yield book


async def test_detached_books_are_the_subscribers_own():
  """Mutating a detached book leaves the shared book intact; `levels` trims."""
  shared = deep_book()
  seen = levels(shared)
  (mine,) = [b async for b in detached_books(stream(shared))]
  (trimmed,) = [b async for b in detached_books(stream(shared), 3)]
  assert levels(mine) == seen and mine.time == T
  assert levels(trimmed) == (seen[0][:3], seen[1][:3])
  mine.buy(qty=Decimal(100))
  mine.sell(qty=Decimal(100))
  mine.asks[0].qty = Decimal(0)
  trimmed.bids.clear()
  assert levels(shared) == seen


async def test_detached_books_copy_only_the_books_read(monkeypatch: pytest.MonkeyPatch):
  """Copy on read: books replaced in a `'latest'` inbox are never copied, and the
  stream keeps reporting them as skipped."""
  copies = 0
  original = Book.copy

  def counted(self: Book) -> Book:
    nonlocal copies
    copies += 1
    return original(self)

  monkeypatch.setattr(Book, 'copy', counted)
  inbox = StreamInbox[Book].new(1, 'latest')
  books = detached_books(inbox)
  for _ in range(100):
    inbox.push(deep_book().frozen())
  inbox.close()
  read = [b async for b in books]
  assert len(read) == 1 and copies == 1
  assert skipped(books) == 99


async def test_subscribers_never_see_a_book_mutated_under_them():
  """End to end over `Subscription`: one subscriber mutates every book it gets, the
  other keeps them all; each kept book still equals the venue state it was sent at."""
  updates = deltas(300)
  expected: list[tuple[list[tuple[Decimal, Decimal]], ...]] = []
  reference = deep_book()
  for delta in updates:
    reference.update(delta)
    expected.append(levels(reference))

  subscribed = asyncio.Barrier(3)

  async def produce() -> AsyncIterator[Book]:
    await subscribed.wait()
    book = deep_book()
    for delta in updates:
      book.update(delta)
      yield book.frozen()
      await asyncio.sleep(0)

  async def subscribe():
    return Subscription.Context(produce(), unsubscribe=lambda: asyncio.sleep(0))

  subscription = Subscription[Book](subscribe)
  kept: list[Book] = []

  async def keeper():
    async with subscription.subscribe(queue_size=1000) as inbox:
      await subscribed.wait()
      async for book in detached_books(inbox):
        kept.append(book)
        if len(kept) == len(updates):
          return

  async def mutator():
    async with subscription.subscribe(queue_size=1000) as inbox:
      await subscribed.wait()
      received = 0
      async for book in detached_books(inbox):
        book.buy(qty=Decimal(3))
        book.sell(qty=Decimal(3))
        for e in book.bids + book.asks:
          e.qty = Decimal(-1)
        received += 1
        if received == len(updates):
          return

  async with asyncio.timeout(10):
    await asyncio.gather(keeper(), mutator())
  assert [levels(b) for b in kept] == expected
