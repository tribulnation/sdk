"""Regression tests for defects found mapping the Bit2Me market surface."""

from decimal import Decimal

from tribulnation.sdk.market import Book
from tribulnation.bit2me.market.impl.depth import parse_levels
from tribulnation.bit2me.market.impl.rules import standard_fees


def test_a_three_element_level_is_read_by_index():
  """Some order-book rows are `[price, amount, notional]`, not a pair.

  Unpacking such a row raises `ValueError`. Which shape arrives is not a property of
  the market: `B2M/EUR` has been seen serving triples over REST while pushing pairs
  over the socket in the same minute, so only the row's own length decides. The three
  majors any live check would reach send pairs, so the fault never shows up there.
  """
  levels = parse_levels([(0.0052283, 76289.74336778, 398.86566524976416)])
  assert levels == [
    Book.Entry(price=Decimal('0.0052283'), qty=Decimal('76289.74336778'))
  ]


def test_standard_fees_distinguish_documented_pair_classes():
  """Stable-base markets have a separate fee tier; unknown classes stay unknown."""
  crypto = standard_fees('BTC', 'EUR')
  stable = standard_fees('USDC', 'EUR')
  assert crypto is not None and stable is not None
  assert crypto.maker_buy == crypto.maker_sell == Decimal('0.005')
  assert crypto.taker_buy == crypto.taker_sell == Decimal('0.006')
  assert stable.maker_buy == stable.maker_sell == Decimal(0)
  assert stable.taker_buy == stable.taker_sell == Decimal('0.0001')
  assert standard_fees('UNCLASSIFIED', 'EUR') is None
