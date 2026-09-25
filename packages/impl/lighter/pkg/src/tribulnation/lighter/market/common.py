"""Shared base object, venue settings and the venue-row parsers perp and spot share."""

from dataclasses import dataclass
from decimal import Decimal

from typing_extensions import AsyncContextManager, Iterable, TypedDict
from typed_lighter.schemas import (
  Candle as CandleRow,
  Order as OrderRow,
  Trade as TradeRow,
)
from tribulnation.sdk import SDK
from tribulnation.sdk.market import Candle, OrderState, Trade

from ..core import FEE_TICK, Shared


class Settings(TypedDict, total=False):
  """Lighter order settings, under `settings['lighter']`."""

  reduce_only: bool
  """Only ever reduce the position. Defaults to false."""


ACTIVE_STATUSES = frozenset({'in-progress', 'pending', 'open'})
"""Order statuses of an order still live on the book (or awaiting its trigger)."""


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange and market objects."""

  shared: Shared

  @property
  def venue_id(self) -> str:
    """The Catalogue platform ID."""
    return 'lighter'

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared


def parse_order(o: OrderRow) -> OrderState:
  """An order's state; the SDK id is the `client_order_index`, sells are negative."""
  sign = -1 if o['is_ask'] else 1
  return OrderState(
    id=o['client_order_id'],
    price=o['price'],
    qty=o['initial_base_amount'] * sign,
    filled_qty=o['filled_base_amount'] * sign,
    active=o['status'] in ACTIVE_STATUSES,
    details=o,
  )


def role(t: TradeRow, account: int) -> tuple[bool, bool, Decimal]:
  """Whether `account` sold, whether it was the maker, and its fee rate."""
  is_ask = t['ask_account_id'] == account
  maker = t['is_maker_ask'] == is_ask
  tick = t.get('maker_fee', 0) if maker else t.get('taker_fee', 0)
  return is_ask, maker, tick * FEE_TICK


def parse_trade(t: TradeRow, account: int, fee: Trade.Fee) -> Trade:
  """The account's fill; `time` is the trade's block timestamp, the venue's own sort key."""
  is_ask = t['ask_account_id'] == account
  return Trade(
    id=t['trade_id_str'],
    price=t['price'],
    qty=-t['size'] if is_ask else t['size'],
    time=t['timestamp'],
    maker=t['is_maker_ask'] == is_ask,
    fee=fee,
    details=t,
  )


def parse_candle(c: CandleRow) -> Candle:
  """A candle; the venue omits zero fields, and `i` is the last trade id, not a count."""
  return Candle(
    time=c['t'],
    open=Decimal(str(c.get('o', 0))),
    high=Decimal(str(c.get('h', 0))),
    low=Decimal(str(c.get('l', 0))),
    close=Decimal(str(c.get('c', 0))),
    volume=Decimal(str(c.get('v', 0))),
    quote_volume=Decimal(str(c.get('V', 0))),
  )
