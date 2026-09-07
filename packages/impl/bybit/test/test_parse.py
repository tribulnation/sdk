"""Regression tests for defects found mapping Bybit payloads onto SDK market types."""

from typing_extensions import Any, cast
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.bybit.market.impl import parse_execution
from typed_bybit.trade.trade_history import Execution


def execution(**overrides: Any) -> Execution:
  """One spot fill, with only the fields the mapping reads."""
  row: dict[str, Any] = {
    'execId': '1',
    'execQty': Decimal('200'),
    'execPrice': Decimal('0.9997'),
    'execTime': datetime(2025, 7, 23, 17, 42, 37, tzinfo=timezone.utc),
    'side': 'Buy',
    'isMaker': True,
    'execFee': Decimal(0),
    'feeCurrency': 'USDC',
  }
  return cast(Execution, {**row, **overrides})


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
