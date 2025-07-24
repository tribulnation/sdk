from .depth import Depth
from .exchange_info import ExchangeInfo
from .time import Time

class MarketData(Depth, ExchangeInfo, Time):
  ...