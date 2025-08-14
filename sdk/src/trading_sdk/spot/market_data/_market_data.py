from .depth import Depth
from .exchange_info import ExchangeInfo
from .time import Time
from .agg_trades import AggTrades

class MarketData(Depth, ExchangeInfo, Time, AggTrades):
  ...