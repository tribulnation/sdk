"""Aster book snapshots keep their exchange event/output time `E` (else `T`), on REST and WS."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from typed_core.validation import validator
from typed_aster.futures.market.depth import Depth as FuturesDepth
from typed_aster.futures.market.depth import OrderBookResponse
from typed_aster.schemas import DepthUpdate, OrderBook
from typed_aster.spot.market.depth import Depth as SpotDepth
from typing_extensions import Any, Literal, cast

from tribulnation.aster import AsterMarket
from tribulnation.aster.core import Scope
from tribulnation.aster.market.markets import PerpMarket, SpotMarket
from tribulnation.aster.market.streams import parse_book

TIME_MS = 1791370594322
TIME = datetime(2026, 10, 7, 10, 56, 34, 322000, tzinfo=timezone.utc)
"""The transaction time `T`."""
EVENT = TIME + timedelta(milliseconds=5)
"""The event/output time `E`, five milliseconds after `T`."""


def rest_wire() -> dict[str, Any]:
  """A raw REST `depth` payload, as Aster sends it."""
  return {
    'lastUpdateId': 1,
    'E': TIME_MS + 5,
    'T': TIME_MS,
    'symbol': 'BTCUSDT',
    'bids': [['100', '1'], ['99', '2']],
    'asks': [['101', '3'], ['102', '4']],
  }


def ws_wire() -> dict[str, Any]:
  """A raw partial-depth WS message, as Aster sends it."""
  return {
    'e': 'depthUpdate',
    'E': TIME_MS + 5,
    'T': TIME_MS,
    's': 'BTCUSDT',
    'U': 1,
    'u': 2,
    'pu': 0,
    'b': [['100', '1'], ['99', '2']],
    'a': [['101', '3'], ['102', '4']],
  }


def unvalidated(wire: dict[str, Any], *, sides: tuple[str, str]) -> dict[str, Any]:
  """The payload with decimal levels but raw `E`/`T`, isolating time handling."""
  return wire | {
    side: [(Decimal(p), Decimal(q)) for p, q in wire[side]] for side in sides
  }


def test_parse_validated_time():
  """A validated WS snapshot decodes `E`, not `T`, to an aware UTC time."""
  book = parse_book(validator(DepthUpdate).python(ws_wire()))
  assert book.time == EVENT
  assert book.time is not None and book.time.utcoffset() is not None
  assert book.best_bid.price == Decimal('100')
  assert book.best_ask.price == Decimal('101')


def test_parse_unvalidated_time():
  """An unvalidated message's millisecond epoch converts to the same datetime."""
  row = unvalidated(ws_wire(), sides=('b', 'a'))
  assert parse_book(cast(DepthUpdate, row)).time == EVENT
  assert parse_book(cast(DepthUpdate, row | {'E': str(TIME_MS + 5)})).time == EVENT


def test_parse_falls_back_to_transaction_time():
  """A message without `E` keeps `T`; one with neither has no time."""
  row: dict[str, Any] = dict(validator(DepthUpdate).python(ws_wire()))
  del row['E']
  assert parse_book(cast(DepthUpdate, row)).time == TIME
  del row['T']
  assert parse_book(cast(DepthUpdate, row)).time is None


def market(venue: AsterMarket, scope: Scope) -> SpotMarket | PerpMarket:
  """A market sharing the venue's owner, without catalogue requests."""
  cls = PerpMarket if scope == 'perp' else SpotMarket
  return cls(shared=venue.shared, symbol='BTCUSDT')


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize('validate', [True, False])
@pytest.mark.parametrize('present', ['E', 'T', None])
async def test_depth_time(
  scope: Scope,
  validate: bool,
  present: Literal['E', 'T'] | None,
  monkeypatch: pytest.MonkeyPatch,
):
  """REST `depth` carries `E` (else `T`) whether or not validated, else None."""
  Type = OrderBook if scope == 'spot' else OrderBookResponse
  payload: dict[str, Any] = (
    dict(validator(Type).python(rest_wire()))
    if validate
    else unvalidated(rest_wire(), sides=('bids', 'asks'))
  )
  if present != 'E':
    del payload['E']
  if present is None:
    del payload['T']

  async def depth(self: object, symbol: str, **_: Any):
    """Return the fixture payload, as the typed client would."""
    assert symbol == 'BTCUSDT'
    return payload

  monkeypatch.setattr(SpotDepth if scope == 'spot' else FuturesDepth, 'depth', depth)
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    book = await market(venue, scope).depth(levels=1)
  assert book.time == {'E': EVENT, 'T': TIME, None: None}[present]
  assert [e.price for e in book.bids] == [Decimal('100')]
