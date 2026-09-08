"""Regression tests for defects found mapping Bybit payloads onto SDK market types."""

from typing_extensions import Any, cast
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.bybit.market.impl import parse_execution
from typed_bybit.private.execution import ExecutionUpdate
from typed_bybit.trade.trade_history import Execution

ROW: dict[str, Any] = {
  'execId': '1',
  'execQty': Decimal('200'),
  'execPrice': Decimal('0.9997'),
  'execTime': datetime(2025, 7, 23, 17, 42, 37, tzinfo=timezone.utc),
  'side': 'Buy',
  'isMaker': True,
  'execFee': Decimal(0),
  'feeCurrency': 'USDC',
}
"""One spot fill, with only the fields the mapping reads."""


def execution(**overrides: Any) -> Execution:
  """That fill as the REST endpoint reports it."""
  return cast(Execution, {**ROW, **overrides})


def execution_update(**overrides: Any) -> ExecutionUpdate:
  """That fill as the private `execution` stream pushes it."""
  return cast(
    ExecutionUpdate, {**ROW, 'category': 'spot', 'symbol': 'BTCUSDC', **overrides}
  )


def test_a_zero_execution_fee_is_reported_not_dropped():
  """A truthiness guard on `execFee` reported a real zero fee as "fee unknown".

  40 of the 55 spot fills on the reference account carry `execFee == 0`, so most of
  the history came back `fee=None`. Whether a live sweep catches the regression
  depends on the account still holding fee-free fills in the queried window.
  """
  trade = parse_execution(execution())
  assert trade.fee is not None
  assert trade.fee.amount == Decimal(0)
  assert trade.fee.asset == 'USDC'


def test_a_streamed_fill_maps_the_same_as_its_rest_twin():
  """One mapping serves both shapes only while they agree field for field.

  The stream once sent its sizes and fees as unparsed strings, which needed a second
  mapping; should they diverge again, the sizes come back multiplied by nothing and
  the difference is invisible until a number is wrong downstream.
  """
  rest = parse_execution(execution())
  streamed = parse_execution(execution_update())
  assert (streamed.id, streamed.price, streamed.qty) == (rest.id, rest.price, rest.qty)
  assert (streamed.time, streamed.maker) == (rest.time, rest.maker)
  assert streamed.fee == rest.fee
