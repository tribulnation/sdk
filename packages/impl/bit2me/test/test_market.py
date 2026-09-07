"""Regression tests for defects found mapping the Bit2Me market surface."""

from decimal import Decimal

from tribulnation.sdk.market import Book
from tribulnation.bit2me.market.impl.depth import parse_levels


def test_a_three_element_level_is_read_by_index():
  """26 of Bit2Me's 290 markets send `[price, amount, notional]`, not a pair.

  Unpacking the row raised `ValueError` on every one of them -- the thin and
  stablecoin pairs (B2M/EUR, HTX/USDC, BTC/EURCV, ...). The three majors any live
  check would reach all send two-element rows, so the fault never shows up there.
  """
  levels = parse_levels([(0.0052283, 76289.74336778, 398.86566524976416)])
  assert levels == [
    Book.Entry(price=Decimal('0.0052283'), qty=Decimal('76289.74336778'))
  ]
