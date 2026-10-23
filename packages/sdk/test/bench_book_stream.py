"""Per-update cost of maintaining and handing out a streamed order book.

Not collected by pytest. Run it with `python packages/sdk/test/bench_book_stream.py`.

The book is 500 levels a side and takes 1000 random deltas of 1 to 4 levels a side
(changes, additions and removals), as diff feeds such as Bitget's `books` channel
send them. Each scenario runs `Book.update` and then the copying a stream does per
update:

1. `deepcopy` is the previous `Book.copy`, taken by the producer per update.
2. `frozen` replaces it in the producer; `copy` is what `detached_books` takes, once
   per book a subscriber reads.

CPU is measured with tracing off, and allocations in a second pass under
`tracemalloc`, as the peak bytes allocated by one update and its copies.
"""

import copy
import random
import time
import tracemalloc
from decimal import Decimal

from typing_extensions import Callable

from tribulnation.sdk.market import Book

DEPTH = 500
UPDATES = 1000


def initial_book() -> Book:
  """A book `DEPTH` levels a side around 50000, with two-decimal prices."""
  rng = random.Random(1)
  return Book(
    bids=[
      Book.Entry(Decimal(5_000_000 - i) / 100, Decimal(rng.randint(1, 99_999)) / 1000)
      for i in range(DEPTH)
    ],
    asks=[
      Book.Entry(Decimal(5_000_001 + i) / 100, Decimal(rng.randint(1, 99_999)) / 1000)
      for i in range(DEPTH)
    ],
  )


def deltas() -> list[Book]:
  """`UPDATES` deltas inside the book's price range, a quarter of the levels removals."""
  rng = random.Random(2)

  def side(lo: int, hi: int) -> list[Book.Entry]:
    return [
      Book.Entry(
        Decimal(rng.randint(lo, hi)) / 100,
        Decimal(0) if rng.random() < 0.25 else Decimal(rng.randint(1, 99_999)) / 1000,
      )
      for _ in range(rng.randint(1, 4))
    ]

  return [
    Book(
      bids=side(5_000_000 - DEPTH, 5_000_000), asks=side(5_000_001, 5_000_001 + DEPTH)
    )
    for _ in range(UPDATES)
  ]


Step = Callable[[Book], object]

SCENARIOS: dict[str, Step] = {
  'update only': lambda book: None,
  'before: update + deepcopy (bitget, bybit, kraken, mexc, coinbase)': copy.deepcopy,
  'before: update + deepcopy + deepcopy per subscriber (lighter, grvt)': lambda book: (
    copy.deepcopy(copy.deepcopy(book))
  ),
  'after: update + frozen (book skipped by the subscriber)': Book.frozen,
  'after: update + frozen + copy (book read by the subscriber)': lambda book: (
    book.frozen().copy()
  ),
}


def cpu(step: Step, updates: list[Book]) -> float:
  """Mean CPU microseconds per update."""
  book = initial_book()
  start = time.process_time()
  for delta in updates:
    book.update(delta)
    step(book)
  return (time.process_time() - start) / len(updates) * 1e6


def allocated(step: Step, updates: list[Book]) -> float:
  """Mean peak KiB allocated by one update and its copies."""
  book = initial_book()
  total = 0
  tracemalloc.start()
  for delta in updates:
    base = tracemalloc.get_traced_memory()[0]
    tracemalloc.reset_peak()
    book.update(delta)
    result = step(book)
    total += tracemalloc.get_traced_memory()[1] - base
    del result
  tracemalloc.stop()
  return total / len(updates) / 1024


def main():
  """Print one row per scenario."""
  updates = deltas()
  print(f'{DEPTH} levels a side, {UPDATES} updates')
  print(f'{"scenario":<72} {"CPU µs/update":>14} {"KiB/update":>11}')
  for name, step in SCENARIOS.items():
    print(f'{name:<72} {cpu(step, updates):>14.0f} {allocated(step, updates):>11.1f}')


if __name__ == '__main__':
  main()
