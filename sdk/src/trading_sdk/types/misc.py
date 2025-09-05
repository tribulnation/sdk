from decimal import Decimal

Num = Decimal | str | float | int

def fmt_num(num: Num) -> str:
  if isinstance(num, str):
    return num
  else:
    return f'{num:f}'