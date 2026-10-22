"""Shared base object and the venue-row parsers the market objects share."""

from dataclasses import dataclass
from decimal import Decimal

from typing_extensions import AsyncContextManager, Iterable
from typed_grvt.schemas import (
  Candlestick,
  Fill,
  InstrumentDisplay,
  Order as GrvtOrder,
)
from tribulnation.sdk import SDK
from tribulnation.sdk.market import Candle, OrderState, Trade

from ..core import Shared, VenueId

ACTIVE_STATUSES = frozenset({'PENDING', 'OPEN'})
"""Statuses of an order still live: accepted but not yet processed, or resting."""


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange and market objects."""

  shared: Shared

  @property
  def venue_id(self) -> VenueId:
    """The deployment's venue ID: `'grvt'`, or `'grvt_testnet'`."""
    return self.shared.venue_id

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.shared.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared


def scope(instrument: InstrumentDisplay) -> tuple[list[str], list[str]]:
  """The base and quote filters naming one perpetual: GRVT lists one perpetual per
  base and quote, and filters orders, fills and positions by them, never by name."""
  return [instrument['base']], [instrument['quote']]


def parse_order(o: GrvtOrder) -> OrderState:
  """A single-leg order's state; the SDK id is its client order id, sells are negative.

  A market order carries no limit price, so its `price` is `0`.
  """
  leg = o['legs'][0]
  sign = 1 if leg['is_buying_asset'] else -1
  state = o.get('state')
  traded = (state['traded_size'] if state is not None else None) or [Decimal(0)]
  return OrderState(
    id=o['metadata']['client_order_id'],
    price=leg.get('limit_price', Decimal(0)),
    qty=sign * leg['size'],
    filled_qty=sign * traded[0],
    active=state is not None and state['status'] in ACTIVE_STATUSES,
    details=o,
  )


def parse_fill(f: Fill) -> Trade:
  """The account's fill, signed by side.

  `order_id` and `client_order_id` are both the order's client order id, the SDK order
  id. The fee is the venue's `fee` in `fee_currency` (negative for a maker rebate); a
  builder fee is a separate `builder_fee`, not added.
  """
  client_order_id = f['client_order_id'] or None
  return Trade(
    id=f['trade_id'],
    order_id=client_order_id,
    client_order_id=client_order_id,
    price=f['price'],
    qty=f['size'] if f['is_buyer'] else -f['size'],
    time=f['event_time'],
    maker=not f['is_taker'],
    fee=Trade.Fee(amount=f['fee'], asset=f['fee_currency']),
    details=f,
  )


def parse_candle(c: Candlestick) -> Candle:
  """A trade candle, with base and quote volumes and the trade count."""
  return Candle(
    time=c['open_time'],
    open=c['open'],
    high=c['high'],
    low=c['low'],
    close=c['close'],
    volume=c['volume_b'],
    quote_volume=c['volume_q'],
    trades=c['trades'],
  )
