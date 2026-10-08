"""`Book.time`, the exchange snapshot timestamp, survives derived books and the wire."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tribulnation.sdk.gateway import codec
from tribulnation.sdk.market import Book, Fees

TIME = datetime(2026, 10, 7, 10, 56, 34, 322000, tzinfo=timezone.utc)


def book(time: datetime | None = TIME) -> Book:
  """A two-level book stamped with `time`."""
  return Book(
    bids=[
      Book.Entry(Decimal('100'), Decimal('1')),
      Book.Entry(Decimal('99'), Decimal('2')),
    ],
    asks=[
      Book.Entry(Decimal('101'), Decimal('3')),
      Book.Entry(Decimal('102'), Decimal('4')),
    ],
    time=time,
  )


def test_time_defaults_to_none():
  """Existing constructors keep working and leave the time unknown."""
  assert Book().time is None
  assert Book(bids=[], asks=[]).time is None


def test_derived_books_keep_time():
  """`limit`, `with_fees` and `copy` keep the snapshot time."""
  fees = Fees.symmetric(maker=Decimal('0.0001'), taker=Decimal('0.0005'))
  assert book().limit(1).time == TIME
  assert book().with_fees(Decimal('0.001')).time == TIME
  assert book().with_fees(fees, maker=True).time == TIME
  assert book().copy().time == TIME


def test_merge_takes_oldest_time():
  """A merged book is only as fresh as its stalest input."""
  older = TIME - timedelta(seconds=5)
  assert book().merge(book(older)).time == older
  assert book(older).merge(book()).time == older
  assert book().merge(book(None)).time is None
  assert book().merge().time == TIME


def test_update_takes_update_time():
  """Applying a stamped delta advances the time; an unstamped one leaves it."""
  local = book()
  later = TIME + timedelta(seconds=1)
  local.update(Book(bids=[Book.Entry(Decimal('100'), Decimal('0'))], time=later))
  assert local.time == later
  assert local.best_bid.price == Decimal('99')
  local.update(Book(asks=[Book.Entry(Decimal('101'), Decimal('5'))]))
  assert local.time == later


def prices(entries: list[Book.Entry]) -> list[Decimal]:
  """Prices of `entries`, in book order."""
  return [e.price for e in entries]


def test_update_without_crossing_is_unchanged():
  """Replacing, adding and removing levels that cross nothing leaves the other side."""
  local = book()
  local.update(
    Book(
      bids=[
        Book.Entry(Decimal('100'), Decimal('5')),
        Book.Entry(Decimal('98'), Decimal('1')),
        Book.Entry(Decimal('99'), Decimal('0')),
      ],
      asks=[Book.Entry(Decimal('103'), Decimal('1'))],
    )
  )
  assert local.bids == [
    Book.Entry(Decimal('100'), Decimal('5')),
    Book.Entry(Decimal('98'), Decimal('1')),
  ]
  assert local.asks == [
    Book.Entry(Decimal('101'), Decimal('3')),
    Book.Entry(Decimal('102'), Decimal('4')),
    Book.Entry(Decimal('103'), Decimal('1')),
  ]


def test_update_bid_removes_crossed_asks():
  """A bid at `p` removes existing asks at or below `p`, including an equal price."""
  local = book()
  local.update(Book(bids=[Book.Entry(Decimal('101'), Decimal('2'))]))
  assert prices(local.bids) == [Decimal('101'), Decimal('100'), Decimal('99')]
  assert local.asks == [Book.Entry(Decimal('102'), Decimal('4'))]

  local = book()
  local.update(Book(bids=[Book.Entry(Decimal('101.5'), Decimal('2'))]))
  assert prices(local.asks) == [Decimal('102')]


def test_update_ask_removes_crossed_bids():
  """An ask at `p` removes existing bids at or above `p`."""
  local = book()
  local.update(Book(asks=[Book.Entry(Decimal('99'), Decimal('1'))]))
  assert local.bids == []
  assert prices(local.asks) == [Decimal('99'), Decimal('101'), Decimal('102')]

  local = book()
  local.update(Book(asks=[Book.Entry(Decimal('99.5'), Decimal('1'))]))
  assert prices(local.bids) == [Decimal('99')]


def test_update_removal_does_not_uncross():
  """A zero-quantity level only removes its own price, even past the other side."""
  local = book()
  local.update(
    Book(
      bids=[Book.Entry(Decimal('101'), Decimal('0'))],
      asks=[Book.Entry(Decimal('100'), Decimal('0'))],
    )
  )
  assert prices(local.bids) == [Decimal('100'), Decimal('99')]
  assert prices(local.asks) == [Decimal('101'), Decimal('102')]


def test_update_crossing_itself_keeps_larger_ask():
  """Crossing levels from one update: the larger (or equal) ask removes the bid."""
  for bid_qty in (Decimal('1'), Decimal('2')):
    local = book()
    local.update(
      Book(
        bids=[Book.Entry(Decimal('101'), bid_qty)],
        asks=[Book.Entry(Decimal('100'), Decimal('2'))],
      )
    )
    assert local.bids == [Book.Entry(Decimal('99'), Decimal('2'))]
    assert local.asks == [
      Book.Entry(Decimal('100'), Decimal('2')),
      Book.Entry(Decimal('101'), Decimal('3')),
      Book.Entry(Decimal('102'), Decimal('4')),
    ]


def test_update_crossing_itself_keeps_larger_bid():
  """Crossing levels from one update: a larger bid removes the ask."""
  local = book()
  local.update(
    Book(
      bids=[Book.Entry(Decimal('101'), Decimal('3'))],
      asks=[Book.Entry(Decimal('100'), Decimal('2'))],
    )
  )
  assert local.bids == [
    Book.Entry(Decimal('101'), Decimal('3')),
    Book.Entry(Decimal('100'), Decimal('1')),
    Book.Entry(Decimal('99'), Decimal('2')),
  ]
  assert local.asks == [Book.Entry(Decimal('102'), Decimal('4'))]


def test_update_leaves_existing_crossings():
  """Crossings between existing levels, e.g. from a crossed snapshot, are kept."""
  local = Book(
    bids=[Book.Entry(Decimal('101'), Decimal('1'))],
    asks=[Book.Entry(Decimal('100'), Decimal('1'))],
  )
  local.update(Book(bids=[Book.Entry(Decimal('90'), Decimal('1'))]))
  assert prices(local.bids) == [Decimal('101'), Decimal('90')]
  assert prices(local.asks) == [Decimal('100')]


def test_codec_round_trip():
  """Gateway depth responses and stream messages carry the time intact."""
  for time in (TIME, None):
    resp = codec.decode_server(
      codec.encode_server(codec.DepthResp(id='1', book=book(time)))
    )
    assert isinstance(resp, codec.DepthResp)
    assert resp.book == book(time)
    assert resp.book.time == time
    msg = codec.decode_server(
      codec.encode_server(codec.DepthDataMsg(id='1', book=book(time)))
    )
    assert isinstance(msg, codec.DepthDataMsg)
    assert msg.book.time == time


def test_codec_decodes_frames_without_time():
  """Frames from a gateway that predates `time` still decode, with no time."""
  frame = b'{"id":"1","book":{"bids":[],"asks":[]},"tag":"depth"}'
  resp = codec.decode_server(frame)
  assert isinstance(resp, codec.DepthResp)
  assert resp.book.time is None
