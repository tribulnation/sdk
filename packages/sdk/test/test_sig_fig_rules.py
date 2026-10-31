"""`Rules.sig_figs`: a price step that grows with the price, integers always valid."""

from decimal import Decimal

import pytest

from tribulnation.sdk.market import Rules


def rules(sig_figs: int | None = 5) -> Rules:
  """Hyperliquid-like rules: 6 decimals at most, 5 significant figures."""
  return Rules(
    fee_asset=None,
    tick_size=Decimal('0.000001'),
    step_size=Decimal('0.01'),
    api=True,
    sig_figs=sig_figs,
  )


@pytest.mark.parametrize(
  ('price', 'step'),
  [
    ('0.0001234', '0.000001'),
    ('0.12345', '0.00001'),
    ('1.2345', '0.0001'),
    ('12345.6', '1'),
    ('123456', '1'),
    ('0', '0.000001'),
  ],
)
def test_price_step_follows_significant_figures(price: str, step: str):
  """The last significant figure's step, between the tick and 1."""
  assert rules().price_step(Decimal(price)) == Decimal(step)


@pytest.mark.parametrize(
  ('price', 'trunc', 'ceil', 'rounded'),
  [
    ('1.23456', '1.2345', '1.2346', '1.2346'),
    ('84512.37', '84512', '84513', '84512'),
    ('9.99996', '9.9999', '10', '10'),
  ],
)
def test_rounding_lands_on_the_grid(price: str, trunc: str, ceil: str, rounded: str):
  """Truncating, ceiling and rounding give valid prices."""
  r = rules()
  p = Decimal(price)
  assert (r.trunc_price(p), r.ceil_price(p), r.round_price(p)) == (
    Decimal(trunc),
    Decimal(ceil),
    Decimal(rounded),
  )
  assert all(r.valid_price(x) for x in (r.trunc_price(p), r.ceil_price(p)))


def test_valid_price():
  """Off-grid prices are invalid; integers of any size are valid."""
  r = rules()
  assert not r.valid_price(Decimal('1.23456'))
  assert r.valid_price(Decimal('1234567'))
  assert r.valid_price(Decimal('0.000123'))


def test_without_sig_figs_the_tick_is_fixed():
  """`sig_figs=None` keeps the plain tick grid."""
  assert rules(None).price_step(Decimal('12345.6')) == Decimal('0.000001')
  assert rules(None).trunc_price(Decimal('1.2345678')) == Decimal('1.234567')
