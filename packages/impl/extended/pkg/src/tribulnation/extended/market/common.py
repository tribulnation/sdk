"""Shared base object and the venue-row parsers the market objects share."""

from dataclasses import dataclass
from decimal import Decimal

from typing_extensions import AsyncContextManager, Iterable, Mapping
from typed_extended.account.funding_history import FundingPayment as FundingRow
from typed_extended.account.schemas import Order as OrderRow
from typed_extended.account.trades import AccountTrade
from typed_extended.info.candles import Candle as CandleRow
from typed_extended.info.markets import Market as MarketRow
from typed_extended.streams.account import StreamTrade
from tribulnation.sdk import SDK
from tribulnation.sdk.market import Candle, OrderState, Trade

from ..core import LISTED, Shared, VenueId

ACTIVE_STATUSES = frozenset({'NEW', 'PARTIALLY_FILLED', 'UNTRIGGERED'})
"""Order statuses of an order still live on the book (or awaiting its trigger)."""


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange and market objects."""

  shared: Shared

  @property
  def venue_id(self) -> VenueId:
    """The deployment's venue ID: `'extended'`, or `'extended_testnet'`."""
    return self.shared.venue_id

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.shared.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared


def listed_perps(markets: Mapping[str, MarketRow]) -> list[str]:
  """The perpetuals `markets()` lists: `ACTIVE`, `REDUCE_ONLY` and `PRELISTED` ones."""
  return [
    name
    for name, m in markets.items()
    if m['type'] == 'PERPETUAL' and m['status'] in LISTED
  ]


def price_or_none(value: Decimal) -> Decimal | None:
  """A `marketStats` price, or `None` where the venue sends `0` (no such price)."""
  return value if value != 0 else None


def parse_order(o: OrderRow) -> OrderState:
  """An order's state; the SDK id is Extended's order `id`, sells are negative.

  Raises:
    ValueError: The order has no price (a TP/SL order, which the SDK never places).
  """
  price = o.get('price')
  if price is None:
    raise ValueError(f'Extended order {o["id"]} ({o["type"]}) has no price')
  sign = -1 if o['side'] == 'SELL' else 1
  return OrderState(
    id=str(o['id']),
    price=price,
    qty=o['qty'] * sign,
    filled_qty=(o.get('filledQty') or Decimal(0)) * sign,
    active=o['status'] in ACTIVE_STATUSES,
    details=o,
  )


def parse_trade(t: AccountTrade | StreamTrade, fee_asset: str) -> Trade:
  """The account's fill: `qty` signed by `side`, the fee in the collateral asset.

  `order_id` is Extended's order id, the SDK order id, and `client_order_id` the
  order's `externalId` (the order hash for orders placed without one).
  """
  return Trade(
    id=str(t['id']),
    order_id=str(t['orderId']),
    client_order_id=t.get('externalOrderId'),
    price=t['price'],
    qty=-t['qty'] if t['side'] == 'SELL' else t['qty'],
    time=t['createdTime'],
    maker=not t['isTaker'],
    fee=Trade.Fee(amount=t['fee'], asset=fee_asset),
    details=t,
  )


def funding_received(row: FundingRow) -> Decimal:
  """A funding payment's amount, positive when received: `fundingFee` as the venue
  signs it.

  Observed on testnet (2026-10-22, `1000BONK-USD` at a rate of `+0.000013`, so longs
  paid): the long's row read `-0.000041` and the short's `0.00004`, the changes to their
  balances.
  """
  return row['fundingFee']


def parse_candle(c: CandleRow) -> Candle:
  """A trade candle, stamped with its open time; volume is in the base asset."""
  return Candle(
    time=c['T'], open=c['o'], high=c['h'], low=c['l'], close=c['c'], volume=c.get('v')
  )
