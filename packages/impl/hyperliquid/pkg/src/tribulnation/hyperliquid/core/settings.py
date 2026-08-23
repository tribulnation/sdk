from typing_extensions import Literal, TypedDict
from hyperliquid.exchange.order import TimeInForce

class Settings(TypedDict, total=False):
  reduce_only: bool
  limit_tif: TimeInForce
  index_price: Literal['oracle', 'mark']
  tickers_fetch_depth: bool
  """Whether bulk tickers fetch order books for best bid and ask. Defaults to True."""
  tickers_depth_concurrent: int
  """Maximum concurrent order-book requests used to enrich bulk tickers. Defaults to 20."""
