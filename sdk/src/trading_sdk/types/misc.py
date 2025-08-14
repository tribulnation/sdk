from typing_extensions import Literal, Any
from dataclasses import dataclass
from decimal import Decimal

Side = Literal['BUY', 'SELL']
TimeInForce = Literal['GTC', 'IOC', 'FOK']
Num = Decimal | str | float | int

def fmt_num(num: Num) -> str:
  if isinstance(num, str):
    return num
  else:
    return f'{num:f}'