"""CPU per call of the `Book` paths a gateway and its workers run per streamed book.

Not collected by pytest. Run it with `python packages/sdk/test/bench_book_hot_paths.py`,
on this checkout and on an older one, to compare.

Books are 500 levels a side; `update` applies 1000 random deltas of 1 to 4 levels a
side (changes, additions and a quarter removals), as in `bench_book_stream.py`. CPU is
measured with the garbage collector on, since level allocations are part of the cost.
"""

import random
import time
from decimal import Decimal

from typing_extensions import Callable

from tribulnation.sdk.gateway import codec
from tribulnation.sdk.market import Book

DEPTH = 500
UPDATES = 1000


def sorted_levels() -> tuple[list[Book.Entry], list[Book.Entry]]:
  """Fresh `DEPTH`-level sides around 50000, already in book order."""
  rng = random.Random(1)
  bids = [
    Book.Entry(Decimal(5_000_000 - i) / 100, Decimal(rng.randint(1, 99_999)) / 1000)
    for i in range(DEPTH)
  ]
  asks = [
    Book.Entry(Decimal(5_000_001 + i) / 100, Decimal(rng.randint(1, 99_999)) / 1000)
    for i in range(DEPTH)
  ]
  return bids, asks


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


def per_call(step: Callable[[], object], n: int) -> float:
  """Mean CPU microseconds of `n` calls to `step`."""
  start = time.process_time()
  for _ in range(n):
    step()
  return (time.process_time() - start) / n * 1e6


def main():
  """Print one row per path."""
  bids, asks = sorted_levels()
  book = Book(bids=list(bids), asks=list(asks))
  frame = codec.encode_server(codec.DepthDataMsg(id='1', book=book))
  updates = deltas()
  live = book.copy()
  rows: dict[str, float] = {
    'Book(...) of sorted levels': per_call(
      lambda: Book(bids=list(bids), asks=list(asks)), 2000
    ),
    'decode a depth frame (gateway client)': per_call(
      lambda: codec.decode_server(frame), 500
    ),
    'best_bid + best_ask': per_call(lambda: (book.best_bid, book.best_ask), 20000),
    'copy': per_call(book.copy, 1000),
    'frozen': per_call(book.frozen, 20000),
  }
  pending = iter(updates)
  rows['update (1-4 level delta)'] = per_call(
    lambda: live.update(next(pending)), UPDATES
  )
  print(f'{DEPTH} levels a side')
  print(f'{"path":<44} {"CPU µs/call":>12}')
  for name, cpu in rows.items():
    print(f'{name:<44} {cpu:>12.1f}')


if __name__ == '__main__':
  main()
