from .candles import Candles
from .depth import Depth
from .funding_rate_history import FundingRateHistory
from .info import Info
from .time import Time
from .trades import Trades

class MarketData(Candles, Depth, Info, Time, Trades):
  ...

class PerpMarketData(MarketData, FundingRateHistory):
  ...