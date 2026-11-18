from decimal import Decimal, ROUND_HALF_DOWN, ROUND_FLOOR, ROUND_CEILING

Num = Decimal | str | float | int


def to_decimal(x: Num) -> Decimal:
  """Read a user-supplied number as the decimal it was written as.

  A `Decimal` passes through unchanged. A `float` goes through `str`, its shortest
  round-tripping repr, so `0.1` becomes `Decimal('0.1')` rather than the binary value
  `0.1000000000000000055511151231257827...` that `Decimal(0.1)` yields. A `str` or `int`
  is parsed as-is.

  Examples:
    >>> to_decimal(0.1)
    Decimal('0.1')
  """
  if isinstance(x, Decimal):
    return x
  elif isinstance(x, float):
    return Decimal(str(x))
  else:
    return Decimal(x)


def fmt_num(num: Num) -> str:
  """Format a number in plain notation, without exponent or trailing zeros (`-0` as `0`)."""
  out = f'{to_decimal(num).normalize():f}'
  if out == '-0':
    return '0'
  else:
    return out


def round2tick(x: Decimal, tick_size: Decimal) -> Decimal:
  r = (x / tick_size).quantize(Decimal('1.'), rounding=ROUND_HALF_DOWN) * tick_size
  return r.normalize()


def trunc2tick(x: Decimal, tick_size: Decimal) -> Decimal:
  r = (x / tick_size).to_integral_value(rounding=ROUND_FLOOR) * tick_size
  return r.normalize()


def ceil2tick(x: Decimal, tick_size: Decimal) -> Decimal:
  r = (x / tick_size).to_integral_value(rounding=ROUND_CEILING) * tick_size
  return r.normalize()
