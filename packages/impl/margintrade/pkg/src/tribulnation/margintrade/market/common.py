"""Shared base object and the venue-row parsers markets and exchanges share."""

from dataclasses import dataclass
from decimal import Decimal

from typing_extensions import AsyncContextManager, Iterable
from typed_margintrade.schemas import (
  Candle as CandleRow,
  HistoricalOrder,
  L2Level,
  UserFill,
)
from typed_margintrade.info.frontend_open_orders import FrontendOpenOrder
from tribulnation.sdk import SDK
from tribulnation.sdk.market import Book, Candle, OrderState, Trade

from ..core import USDC, Shared, VenueId


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange and market objects."""

  shared: Shared

  @property
  def venue_id(self) -> VenueId:
    """The network's venue ID: `'margintrade'`, or `'margintrade_testnet'`."""
    return self.shared.venue_id

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.shared.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared


def levels(rows: Iterable[L2Level]) -> list[Book.Entry]:
  """Book entries from venue price levels."""
  return [Book.Entry(r['px'], r['sz']) for r in rows]


def signed(qty: Decimal, side: str) -> Decimal:
  """A quantity signed by side: bids (`B`) positive, asks (`A`) negative."""
  return qty if side == 'B' else -qty


def parse_open_order(o: FrontendOpenOrder) -> OrderState:
  """An open order; the SDK id is the venue order id."""
  return OrderState(
    id=str(o['oid']),
    price=o['limitPx'],
    qty=signed(o['origSz'], o['side']),
    filled_qty=signed(o['origSz'] - o['sz'], o['side']),
    active=True,
    details=o,
  )


def parse_order(o: HistoricalOrder) -> OrderState:
  """An order and its latest status; market orders carry no limit price (0)."""
  detail = o['order']
  return OrderState(
    id=str(detail['oid']),
    price=detail['limitPx'] or Decimal(0),
    qty=signed(detail['origSz'], detail['side']),
    filled_qty=signed(detail['origSz'] - detail['sz'], detail['side']),
    active=o['status'] == 'open',
    details=o,
  )


def parse_fill(f: UserFill) -> Trade:
  """A fill. `isTaker` decides the role: the venue's `crossed` flag is `true` on maker
  fills too. Fees are in USDC whether the venue labels them `USD` or `USDC`; a negative
  fee is a maker rebate."""
  return Trade(
    id=str(f['tid']),
    order_id=str(f['oid']),
    price=f['px'],
    qty=signed(f['sz'], f['side']),
    time=f['time'],
    maker=not f['isTaker'],
    fee=Trade.Fee(amount=f['fee'], asset=USDC),
    details=f,
  )


def parse_candle(c: CandleRow) -> Candle:
  """A candle; volumes are in base units, trade counts are reported."""
  return Candle(
    time=c['t'],
    open=c['o'],
    high=c['h'],
    low=c['l'],
    close=c['c'],
    volume=c['v'],
    trades=c['n'],
  )
