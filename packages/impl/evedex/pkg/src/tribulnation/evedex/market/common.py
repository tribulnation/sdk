"""Shared base object and the venue-row parsers the market objects share."""

from dataclasses import dataclass
from decimal import Decimal

from typing_extensions import AsyncContextManager, Iterable, Literal, Sequence
from typed_evedex.exchange.fills import AccountFill
from typed_evedex.exchange.orders.fills import OrderFillFee
from typed_evedex.exchange.orders.opened import OpenOrder
from typed_evedex.schemas import Order as OrderRow, OrderDetails
from typed_evedex.streams.account.fills import OrderFillUpdate
from tribulnation.sdk import SDK
from tribulnation.sdk.market import OrderState, Trade

from ..core import Shared, VenueId

ACTIVE = frozenset({'INTENTION', 'NEW', 'PARTIALLY_FILLED'})
"""Order statuses still able to fill: accepted (`INTENTION`, processing is asynchronous)
or resting on the book."""


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange and market objects."""

  shared: Shared

  @property
  def venue_id(self) -> VenueId:
    """The venue ID, `'evedex'`."""
    return self.shared.venue_id

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.shared.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared


def signed(side: Literal['BUY', 'SELL'], qty: Decimal) -> Decimal:
  """`qty` signed by `side`: negative for a sell."""
  return -qty if side == 'SELL' else qty


def parse_order(o: OrderRow | OrderDetails | OpenOrder) -> OrderState:
  """An order's state: its size and what filled (`quantity - unFilledQuantity`), signed
  by `side`. A market order's `limitPrice` is `0`."""
  return OrderState(
    id=o['id'],
    price=o['limitPrice'],
    qty=signed(o['side'], o['quantity']),
    filled_qty=signed(o['side'], o['quantity'] - o['unFilledQuantity']),
    active=o['status'] in ACTIVE,
    details=o,
  )


def fill_fee(fees: Sequence[OrderFillFee]) -> Trade.Fee | None:
  """A fill's fee, paid-positive, when the venue charged it in one coin; `None` before
  the asynchronous fee processing has charged it."""
  if len(fees) == 1:
    return Trade.Fee(amount=fees[0]['quantity'], asset=fees[0]['coin'])


def parse_fill(
  f: AccountFill, *, side: Literal['BUY', 'SELL'], fee: Trade.Fee | None
) -> Trade:
  """A history fill, signed by its order's `side`. The order id is also the client
  order id: every EVEDEX order id is chosen by the client that placed it."""
  return Trade(
    id=f['id'],
    order_id=f['order'],
    client_order_id=f['order'],
    price=f['fillPrice'],
    qty=signed(side, f['fillQuantity']),
    time=f['createdAt'],
    maker=f['fillRole'] == 'MAKER',
    fee=fee,
    details=f,
  )


def parse_stream_fill(f: OrderFillUpdate) -> Trade:
  """A fill from the account's `orderFills` channel, which carries no fee."""
  return Trade(
    id=f['executionId'],
    order_id=f['orderId'],
    client_order_id=f['orderId'],
    price=f['fillPrice'],
    qty=signed(f['side'], f['fillQuantity']),
    time=f['createdAt'],
    maker=f['makerTakerFlag'] == 'MAKER',
    details=f,
  )
