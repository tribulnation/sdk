"""Regression tests for defects found mapping Coinbase responses."""

from typing_extensions import Any
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from typed_coinbase.app.advanced_trade.http.orders.historical.batch import (
  Order as PlacedOrder,
)

from tribulnation.coinbase.market.impl.funding import (
  funding_interval,
  next_funding_time,
)
from tribulnation.coinbase.market.impl.orders import parse_order

TIME = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def untouched_order() -> PlacedOrder:
  """Build an open Advanced Trade order with nothing filled against it yet."""
  return {
    'order_id': 'o-1',
    'product_id': 'BTC-USD',
    'user_id': 'u-1',
    'side': 'BUY',
    'order_configuration': {'market_market_ioc': {}},
    'status': 'OPEN',
    'client_order_id': 'c-1',
    'created_time': TIME,
    'completion_percentage': Decimal(0),
    'average_filled_price': Decimal('50000'),
    'number_of_fills': 0,
    'filled_size': Decimal(0),
    'total_fees': Decimal(0),
    'pending_cancel': False,
    'size_in_quote': False,
    'size_inclusive_of_fees': False,
    'total_value_after_fees': Decimal(0),
  }


def test_an_unfilled_order_does_not_divide_by_its_zero_completion() -> None:
  """`Order` carries no original size, so it is backed out of filled / completion.

  A resting order that has never traded reports `completion_percentage` 0, and the
  division raises `ZeroDivisionError` -- taking down the whole `open_orders()` sweep,
  not just the one row. Whether a live account has such an order at any moment is luck.
  """
  assert parse_order(untouched_order()).qty == Decimal(0)


def test_next_funding_time_advances_past_the_last_settlement() -> None:
  """The catalogue's `funding_time` is the settlement that already happened.

  Polled across an hour boundary it held 15:00:00Z for the whole of 15:00-16:00 and
  flipped to 16:00:00Z six seconds after the hour, so reporting it verbatim as
  `NextFunding.time` always names a moment in the past.
  """
  details: dict[str, Any] = {
    'funding_interval': '3600s',
    'perpetual_details': {'funding_time': '2026-09-04T18:00:00.000026Z'},
  }
  assert funding_interval(details) == timedelta(hours=1)
  assert next_funding_time(details) == datetime(
    2026, 9, 4, 19, 0, 0, 26, tzinfo=timezone.utc
  )
