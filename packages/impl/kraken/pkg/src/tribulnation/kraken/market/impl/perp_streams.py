"""Kraken Futures feeds as SDK values: whole books and own fills."""

from typing_extensions import AsyncIterable, AsyncIterator

from tribulnation.sdk.core import NetworkError
from tribulnation.sdk.market import Book, Trade

from typed_kraken.futures_trading.ws import BookLevel, BookMessage, FillsMessage, WsFill


def levels(rows: list[BookLevel]) -> list[Book.Entry]:
  """Book entries of a snapshot side."""
  return [Book.Entry(row['price'], row['qty']) for row in rows]


async def fold_futures_books(
  messages: AsyncIterable[BookMessage], symbol: str
) -> AsyncIterator[Book]:
  """Fold the `book` feed's snapshot and per-level updates into whole books.

  Each update carries one level's new size (0 removes it) and the product's next
  `seq`. A skipped `seq` means a lost update: the stream fails with `NetworkError`, so
  subscribers reconnect and start from a fresh snapshot rather than a wrong book.
  Each yielded book is `Book.frozen`.

  Raises:
    NetworkError: An update arrived out of sequence, or before the snapshot.
  """
  book: Book | None = None
  seq = 0
  async for message in messages:
    if message['feed'] == 'book_snapshot':
      book = Book(
        bids=levels(message['bids']),
        asks=levels(message['asks']),
        time=message['timestamp'],
      )
      seq = message['seq']
    elif book is None or message['seq'] != seq + 1:
      raise NetworkError(
        f'Kraken Futures book {symbol} out of sequence: got {message["seq"]} after {seq}'
      )
    else:
      entry = [Book.Entry(message['price'], message['qty'])]
      if message['side'] == 'buy':
        book.update(Book(bids=entry, time=message['timestamp']))
      else:
        book.update(Book(asks=entry, time=message['timestamp']))
      seq = message['seq']
    yield book.frozen()


async def futures_fills(messages: AsyncIterable[FillsMessage]) -> AsyncIterator[WsFill]:
  """The fills of the `fills` feed after subscribing; the snapshot of past ones is skipped."""
  async for message in messages:
    if message['feed'] == 'fills':
      for fill in message['fills']:
        yield fill


def parse_ws_fill(fill: WsFill) -> Trade:
  """An own fill from the feed, its fee included."""
  qty = fill['qty'] if fill['buy'] else -fill['qty']
  fee = None
  if (paid := fill.get('fee_paid')) is not None and (
    currency := fill.get('fee_currency')
  ) is not None:
    fee = Trade.Fee(amount=paid, asset=currency)
  return Trade(
    id=fill['fill_id'],
    order_id=fill['order_id'],
    client_order_id=fill.get('cli_ord_id'),
    price=fill['price'],
    qty=qty,
    time=fill['time'],
    maker=fill['fill_type'] == 'maker',
    fee=fee,
    details=fill,
  )
