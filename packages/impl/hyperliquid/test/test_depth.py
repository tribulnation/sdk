"""Hyperliquid `l2Book` parsing keeps the exchange snapshot time."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typed_core.validation import validator
from typed_hyperliquid.info.l2_book import L2Book
from typed_hyperliquid.streams.l2_book import L2BookUpdate
from typing_extensions import Any, cast

from tribulnation.hyperliquid.market.impl.depth import depth, depth_stream, parse_book
from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin

TIME_MS = 1791370594322
TIME = datetime(2026, 10, 7, 10, 56, 34, 322000, tzinfo=timezone.utc)


def wire() -> dict[str, Any]:
  """A raw `l2Book` payload, as Hyperliquid sends it."""
  return {
    'coin': 'BTC',
    'time': TIME_MS,
    'levels': [
      [{'px': '100', 'sz': '1', 'n': 1}, {'px': '99', 'sz': '2', 'n': 1}],
      [{'px': '101', 'sz': '3', 'n': 1}, {'px': '102', 'sz': '4', 'n': 2}],
    ],
  }


@pytest.mark.parametrize('Type', [L2Book, L2BookUpdate])
def test_parse_validated_time(Type: type[L2Book] | type[L2BookUpdate]):
  """Validated REST and WS payloads decode `time` to the aware UTC snapshot time."""
  raw: L2Book | L2BookUpdate = validator(Type).python(wire())
  book = parse_book(raw)
  assert book.time == TIME
  assert book.time is not None and book.time.utcoffset() is not None
  assert book.best_bid.price == Decimal('100')
  assert book.best_ask.price == Decimal('101')


def test_parse_unvalidated_time():
  """An unvalidated payload's millisecond epoch converts to the same datetime."""
  book = parse_book(cast(L2Book, wire()))
  assert book.time == TIME
  assert book.time is not None and book.time.tzinfo is not None


def test_parse_levels_keeps_time():
  """Trimming to the top of book keeps the snapshot time."""
  book = parse_book(cast(L2Book, wire()), levels=1)
  assert [e.price for e in book.bids] == [Decimal('100')]
  assert [e.price for e in book.asks] == [Decimal('101')]
  assert book.time == TIME


async def test_depth_populates_time():
  """The REST `depth` snapshot carries the exchange time."""

  async def l2_book(*, coin: str):
    """Return the fixture payload for the requested coin."""
    assert coin == 'BTC'
    return validator(L2Book).python(wire())

  market = SimpleNamespace(
    client=SimpleNamespace(info=SimpleNamespace(l2_book=l2_book)), asset_name='BTC'
  )
  book = await depth(cast(PerpMarketMixin, market))
  assert book.time == TIME


async def test_depth_stream_populates_time():
  """Each WS `l2Book` message yields a book carrying that message's exchange time."""

  @asynccontextmanager
  async def subscribe_l2_book(coin: str, /, **_: Any):
    """Push two validated snapshots, the second one second later."""
    assert coin == 'BTC'
    later = wire() | {'time': TIME_MS + 1000}

    async def messages():
      """Yield the fixture messages."""
      for msg in (wire(), later):
        yield validator(L2BookUpdate).python(msg)

    yield messages()

  market = SimpleNamespace(subscribe_l2_book=subscribe_l2_book, asset_name='BTC')
  async with depth_stream(cast(PerpMarketMixin, market)) as stream:
    times = [book.time async for book in stream]
  assert times == [TIME, TIME.replace(second=TIME.second + 1)]
