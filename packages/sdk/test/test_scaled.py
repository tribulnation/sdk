"""`Book.scaled` and `Rules.scaled` convert contracts of `m` base units to base units."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tribulnation.sdk.market import Book, Fees, Rules

TIME = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
MULTIPLIERS = [Decimal('1000'), Decimal('0.1'), Decimal('25')]


def book() -> Book:
  """A three-level kPEPE-like book, prices per 1000 PEPE."""
  return Book(
    bids=[
      Book.Entry(Decimal('0.010123'), Decimal('1500')),
      Book.Entry(Decimal('0.010122'), Decimal('3200.5')),
      Book.Entry(Decimal('0.010100'), Decimal('10000')),
    ],
    asks=[
      Book.Entry(Decimal('0.010125'), Decimal('800')),
      Book.Entry(Decimal('0.010127'), Decimal('2500.5')),
      Book.Entry(Decimal('0.010150'), Decimal('9000')),
    ],
    time=TIME,
  )


RULES = Rules(
  fee_asset='USDC',
  tick_size=Decimal('0.000001'),
  step_size=Decimal('1'),
  fixed_min_qty=Decimal('5'),
  min_value=Decimal('10'),
  max_qty=Decimal('1000000'),
  fixed_min_price=Decimal('0.000001'),
  rel_min_price=Decimal('0.95'),
  rel_max_price=Decimal('1.05'),
  fixed_max_price=Decimal('100'),
  fees=Fees.symmetric(maker=Decimal('0.00015'), taker=Decimal('0.00045')),
  api=True,
  details={'szDecimals': 0, 'name': 'kPEPE'},
)
"""kPEPE-like rules with every scaled and unscaled field set."""


def rules(**overrides: object) -> Rules:
  """A copy of `RULES` with `overrides` applied."""
  return replace(RULES, **overrides)


@pytest.mark.parametrize('m', MULTIPLIERS)
def test_book_scaled_converts_entries(m: Decimal):
  """Prices divide and quantities multiply by `m`; notionals and `time` are kept."""
  original = book()
  scaled = original.scaled(m)
  for side, scaled_side in ((original.bids, scaled.bids), (original.asks, scaled.asks)):
    assert len(scaled_side) == len(side)
    for e, s in zip(side, scaled_side):
      assert s.price == e.price / m
      assert s.qty == e.qty * m
      assert s.notional == e.notional
  assert scaled.time == TIME


@pytest.mark.parametrize('m', MULTIPLIERS)
def test_book_scaled_leaves_original_unchanged(m: Decimal):
  """The source book and its entries are not mutated."""
  original = book()
  original.scaled(m)
  assert original == book()
  scaled = original.scaled(m)
  scaled.buy(qty=scaled.asks[0].qty)
  assert original == book()


@pytest.mark.parametrize('m', MULTIPLIERS)
@pytest.mark.parametrize('q', [Decimal('500'), Decimal('2000'), Decimal('4000')])
def test_book_scaled_market_prices(m: Decimal, q: Decimal):
  """Filling `q * m` units on the scaled book costs `1 / m` the original price."""
  original = book()
  scaled = original.scaled(m)
  buy = original.market_buy_price(qty=q)
  sell = original.market_sell_price(qty=q)
  assert buy is not None and sell is not None
  assert scaled.market_buy_price(qty=q * m) == buy / m
  assert scaled.market_sell_price(qty=q * m) == sell / m


@pytest.mark.parametrize('m', [Decimal('0'), Decimal('-1'), Decimal('-0.5')])
def test_book_scaled_rejects_non_positive(m: Decimal):
  """A zero or negative multiplier raises ValueError."""
  with pytest.raises(ValueError):
    book().scaled(m)


@pytest.mark.parametrize('m', MULTIPLIERS)
def test_rules_scaled_converts_fields(m: Decimal):
  """Prices divide and quantities multiply by `m`; everything else is unchanged."""
  original = rules()
  scaled = original.scaled(m)
  assert scaled.tick_size == original.tick_size / m
  assert scaled.step_size == original.step_size * m
  assert scaled.fixed_min_qty == Decimal('5') * m
  assert scaled.max_qty == Decimal('1000000') * m
  assert scaled.fixed_min_price == Decimal('0.000001') / m
  assert scaled.fixed_max_price == Decimal('100') / m
  assert scaled.min_value == original.min_value
  assert scaled.rel_min_price == original.rel_min_price
  assert scaled.rel_max_price == original.rel_max_price
  assert scaled.fees == original.fees
  assert scaled.fee_asset == original.fee_asset
  assert scaled.api == original.api
  assert scaled.details is original.details
  assert original == rules()


def test_rules_scaled_keeps_none():
  """Optional fields left unset stay None."""
  scaled = rules(
    fixed_min_qty=None,
    max_qty=None,
    fixed_min_price=None,
    fixed_max_price=None,
    min_value=None,
    rel_min_price=None,
    rel_max_price=None,
    fees=None,
    fee_asset=None,
    details=None,
  ).scaled(Decimal('1000'))
  assert scaled.fixed_min_qty is None
  assert scaled.max_qty is None
  assert scaled.fixed_min_price is None
  assert scaled.fixed_max_price is None
  assert scaled.min_value is None
  assert scaled.rel_min_price is None
  assert scaled.rel_max_price is None
  assert scaled.fees is None
  assert scaled.fee_asset is None
  assert scaled.details is None


@pytest.mark.parametrize('m', [Decimal('0'), Decimal('-1000')])
def test_rules_scaled_rejects_non_positive(m: Decimal):
  """A zero or negative multiplier raises ValueError."""
  with pytest.raises(ValueError):
    rules().scaled(m)


PRICES = [
  Decimal('0.0101234567'),
  Decimal('0.010125'),
  Decimal('3.7'),
  Decimal('0.0005'),
]
EQUIVALENCE_MULTIPLIERS = [Decimal('1000'), Decimal('0.1')]
RULE_VARIANTS = {
  'fixed_min_qty': rules(min_value=None),
  'min_value': rules(fixed_min_qty=None),
  'both': rules(),
  'step_only': rules(fixed_min_qty=None, min_value=None, step_size=Decimal('0.01')),
}


@pytest.mark.parametrize('m', EQUIVALENCE_MULTIPLIERS)
@pytest.mark.parametrize('p', PRICES)
@pytest.mark.parametrize('variant', RULE_VARIANTS)
def test_rules_scaled_min_qty(m: Decimal, p: Decimal, variant: str):
  """The scaled minimum quantity is `m` times the original."""
  original = RULE_VARIANTS[variant]
  assert original.scaled(m).min_qty(p / m) == m * original.min_qty(p)


def test_rules_scaled_min_qty_bound_by_min_value():
  """The min-value case actually binds in the equivalence fixtures."""
  original = rules(fixed_min_qty=None)
  p = Decimal('0.0101234567')
  assert original.min_qty(p) > original.step_size
  assert original.scaled(Decimal('1000')).min_qty(p / 1000) == 1000 * original.min_qty(
    p
  )


@pytest.mark.parametrize('m', EQUIVALENCE_MULTIPLIERS)
@pytest.mark.parametrize('p', PRICES)
def test_rules_scaled_price_rounding(m: Decimal, p: Decimal):
  """Truncating or ceiling a scaled price is the original's, divided by `m`."""
  original = rules()
  scaled = original.scaled(m)
  assert scaled.trunc_price(p / m) == original.trunc_price(p) / m
  assert scaled.ceil_price(p / m) == original.ceil_price(p) / m


@pytest.mark.parametrize('m', EQUIVALENCE_MULTIPLIERS)
@pytest.mark.parametrize('p', PRICES)
@pytest.mark.parametrize(
  'q', [Decimal('1'), Decimal('4.9'), Decimal('987.65'), Decimal('123456.789')]
)
@pytest.mark.parametrize('variant', RULE_VARIANTS)
def test_rules_scaled_trunc_qty(m: Decimal, p: Decimal, q: Decimal, variant: str):
  """Truncating `q * m` scaled units is `m` times the original; too small stays None."""
  original = RULE_VARIANTS[variant]
  expected = original.trunc_qty(q, price=p)
  actual = original.scaled(m).trunc_qty(q * m, price=p / m)
  if expected is None:
    assert actual is None
  else:
    assert actual == m * expected


def test_rules_scaled_trunc_qty_covers_none():
  """The trunc_qty fixtures include a quantity below the minimum."""
  original = rules()
  assert original.trunc_qty(Decimal('1'), price=Decimal('3.7')) is None
  assert (
    original.scaled(Decimal('1000')).trunc_qty(Decimal('1000'), price=Decimal('0.0037'))
    is None
  )
