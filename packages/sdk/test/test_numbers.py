"""`to_decimal` keeps the digits a number was written with, and `fmt_num` builds on it."""

from decimal import Decimal

import pytest

from tribulnation.sdk.util import Num, fmt_num, to_decimal


@pytest.mark.parametrize(
  ('x', 'expected'),
  [
    (0.1, '0.1'),
    (0.3, '0.3'),
    (1e-7, '1E-7'),
    (2345.6, '2345.6'),
    (-0.0, '-0.0'),
    ('0.1', '0.1'),
    ('1E+2', '1E+2'),
    (10**30, '1000000000000000000000000000000'),
    (-5, '-5'),
  ],
)
def test_to_decimal_keeps_the_written_digits(x: Num, expected: str):
  """A float reads as its shortest repr, not its binary expansion; strings and ints as
  written."""
  assert str(to_decimal(x)) == expected


def test_float_is_not_its_binary_expansion():
  """`Decimal(0.1)` is the binary value; `to_decimal(0.1)` is the decimal written."""
  assert Decimal(0.1) != Decimal('0.1')
  assert to_decimal(0.1) == Decimal('0.1')


def test_decimal_passes_through_unchanged():
  """A `Decimal` is returned as the same object, precision and exponent intact."""
  x = Decimal('2.50')
  assert to_decimal(x) is x


@pytest.mark.parametrize(
  ('x', 'expected'),
  [
    (0.1, '0.1'),
    (1e-7, '0.0000001'),
    (10**30, '1000000000000000000000000000000'),
    (1e22, '10000000000000000000000'),
    (-0.0, '0'),
    (Decimal('-0'), '0'),
    (Decimal('2.50'), '2.5'),
    (Decimal('4E+1'), '40'),
    ('0.30', '0.3'),
    (-12, '-12'),
  ],
)
def test_fmt_num_is_positional_and_normalized(x: Num, expected: str):
  """No exponent, no trailing zeros, `-0` as `0`, and floats by their shortest repr."""
  assert fmt_num(x) == expected
