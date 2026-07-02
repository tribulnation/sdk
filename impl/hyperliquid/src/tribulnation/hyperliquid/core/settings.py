from typing_extensions import Literal, TypedDict
from hyperliquid.exchange.order import TimeInForce

class Settings(TypedDict, total=False):
  reduce_only: bool
  limit_tif: TimeInForce
  index_price: Literal['oracle', 'mark']