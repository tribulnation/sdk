from typing_extensions import Literal
from decimal import Decimal

Side = Literal['BUY', 'SELL']
TimeInForce = Literal['GTC', 'IOC', 'FOK']
Num = str | Decimal | int