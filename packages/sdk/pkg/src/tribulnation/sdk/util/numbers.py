from decimal import Decimal, ROUND_HALF_DOWN, ROUND_FLOOR, ROUND_CEILING

Num = Decimal | str | float | int


def fmt_num(num: Num) -> str:
  out = f'{Decimal(num).normalize():f}'
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


def whole_leverage(leverage: Decimal) -> int:
  """`leverage` as the positive whole number venues accept for a leverage setting.

  Raises:
    ValueError: `leverage` is not a positive whole number (NaN and infinities
      included).
  """
  if leverage.is_finite() and leverage > 0 and leverage == leverage.to_integral_value():
    return int(leverage)
  else:
    raise ValueError(f'Leverage must be a positive whole number, got {leverage}')
