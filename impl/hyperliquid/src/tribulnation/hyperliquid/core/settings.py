from typing_extensions import TypedDict, Literal
from hyperliquid.exchange.order import TimeInForce

class Settings(TypedDict, total=False):
  validate: bool
  reduce_only: bool
  limit_tif: TimeInForce
  index_price: Literal['oracle', 'mark']