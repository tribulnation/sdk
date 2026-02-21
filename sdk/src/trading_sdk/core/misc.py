from decimal import Decimal

Num = Decimal | str | float | int

def fmt_num(num: Num) -> str:
  out = f'{Decimal(num).normalize():f}'
  if out == '-0':
    return '0'
  else:
    return out