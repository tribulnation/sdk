"""Shared base object and the venue-row parsers the market objects share."""

from dataclasses import dataclass
from decimal import Decimal

from typing_extensions import AsyncContextManager, Iterable
from typed_risex.account.funding_payments import FundingPayment as FundingRow
from typed_risex.account.trade_history import AccountTrade
from typed_risex.schemas import Order as OrderRow
from typed_risex.streams.fills import StreamFill
from tribulnation.sdk import SDK
from tribulnation.sdk.market import OrderState, Trade

from ..core import COLLATERAL, Shared, VenueId


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange and market objects."""

  shared: Shared

  @property
  def venue_id(self) -> VenueId:
    """The deployment's venue ID: `'risex'`, or `'risex_testnet'`."""
    return self.shared.venue_id

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.shared.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared


def parse_order(o: OrderRow) -> OrderState:
  """An order's state: its original size and what filled, signed by `side`.

  The SDK id is the venue's composite order id (`0x` and 48 hex digits).
  """
  sign = -1 if o['side'] == 'SELL' else 1
  return OrderState(
    id=o['id'],
    price=o['price'],
    qty=o['size'] * sign,
    filled_qty=o['filled_size'] * sign,
    active=o['status'] == 'ORDER_STATUS_OPEN',
    details=o,
  )


def parse_trade(t: AccountTrade | StreamFill) -> Trade:
  """The account's fill: `qty` signed by `side`, the fee in USDC, paid-positive.

  `client_order_id` is the order's, `None` where it had none (`''` in history, absent
  on the stream).
  """
  return Trade(
    id=t['id'],
    order_id=t['order_id'],
    client_order_id=t.get('client_order_id') or None,
    price=t['price'],
    qty=-t['size'] if t['side'] == 'SELL' else t['size'],
    time=t['time'],
    maker=t['liquidity_indicator'] == 'MAKER',
    fee=Trade.Fee(amount=t['fee'], asset=COLLATERAL),
    details=t,
  )


def funding_received(row: FundingRow) -> Decimal:
  """A funding payment's amount, positive when received: `funding_payment` negated.

  The venue's `funding_payment` is positive when paid. Testnet (2026-11-16): a 0.0001
  BTC long at a rate of `-0.000750751` (longs receive) reads `-0.004879833131885902`,
  and the account's USDC balance reconciles only with that amount credited. Mainnet
  (2026-11-17): a long at `+0.0000336` reads `+19.47` (paid), a short at `+0.0000054`
  reads `-2.44` (received).
  """
  return -row['funding_payment']
