"""Shared base object and the venue-row parsers the market objects share."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from typing_extensions import AsyncContextManager, Iterable
from typed_nado.archive.orders import ArchiveOrder
from typed_nado.schemas import Candlestick, Match, OpenOrder
from typed_nado.streams.fill import FillEvent
from tribulnation.sdk import SDK
from tribulnation.sdk.market import Candle, OrderState, Trade

from ..core import QUOTE_ASSET, Shared, VenueId, x18


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange and market objects."""

  shared: Shared

  @property
  def venue_id(self) -> VenueId:
    """The deployment's venue ID: `'nado'`, or `'nado_testnet'`."""
    return self.shared.venue_id

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.shared.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared


def client_id(raw: int | None) -> str | None:
  """The SDK client order id of a venue `id`, `None` when the order carried none."""
  return None if raw is None else str(raw)


def parse_open_order(o: OpenOrder) -> OrderState:
  """A resting order; the SDK id is its digest, sells are negative."""
  qty = x18(o['amount'])
  return OrderState(
    id=o['digest'],
    price=x18(o['price_x18']),
    qty=qty,
    filled_qty=qty - x18(o['unfilled_amount']),
    active=True,
    details=o,
  )


def parse_archived_order(o: ArchiveOrder) -> OrderState:
  """An order no longer on the book that filled at least once (the archive indexes no
  other): how much of it filled, inactive."""
  return OrderState(
    id=o['digest'],
    price=x18(o['price_x18']),
    qty=x18(o['amount']),
    filled_qty=x18(o['base_filled']),
    active=False,
    details=o,
  )


def match_price(m: Match) -> Decimal:
  """The fill price: the quote exchanged before fees over the base filled.

  `quote_filled` is net of the fee (fees included, signed as the subaccount's cash
  flow), so the gross quote is `quote_filled + fee`, and the price is its negation over
  `base_filled`. Every archived BTC-PERP fill recorded for typed-nado (2026-11-16, buys
  and sells, all taker) comes out an exact multiple of the 1 USDT0 tick.
  """
  return -(x18(m['quote_filled']) + x18(m['fee'])) / x18(m['base_filled'])


def parse_match(m: Match, time: datetime | None) -> Trade:
  """The account's fill, signed by side, with its fee in USDT0.

  The trade id is `<submission_idx>:<digest>` (one transaction fills one of the
  subaccount's orders at most once), the same id the fills stream gives the fill. The
  fee is the venue's `fee`: trading plus sequencer fee, negative for a rebate; a
  builder fee is a separate `builder_fee`, not added. The archive does not report the
  order's client id.
  """
  return Trade(
    id=f'{m["submission_idx"]}:{m["digest"]}',
    order_id=m['digest'],
    price=match_price(m),
    qty=x18(m['base_filled']),
    time=time,
    maker=not m['is_taker'],
    fee=Trade.Fee(amount=x18(m['fee']), asset=QUOTE_ASSET),
    details=m,
  )


def parse_fill_event(f: FillEvent) -> Trade:
  """A pushed fill, signed by side, with its fee in USDT0 and the order's client id."""
  qty = abs(x18(f['filled_qty']))
  return Trade(
    id=f'{f["submission_idx"]}:{f["order_digest"]}',
    order_id=f['order_digest'],
    client_order_id=client_id(f.get('id')),
    price=x18(f['price']),
    qty=qty if f['is_bid'] else -qty,
    time=f['timestamp'],
    maker=not f['is_taker'],
    fee=Trade.Fee(amount=x18(f['fee']), asset=QUOTE_ASSET),
    details=f,
  )


def parse_candle(c: Candlestick) -> Candle:
  """A trade candle with its base volume; Nado reports no quote volume or trade count."""
  return Candle(
    time=c['timestamp'],
    open=x18(c['open_x18']),
    high=x18(c['high_x18']),
    low=x18(c['low_x18']),
    close=x18(c['close_x18']),
    volume=x18(c['volume']),
  )
