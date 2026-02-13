from dataclasses import dataclass as _dataclass

from tribulnation.sdk.market import MarketData as _MarketData
from .candles import Candles
from .depth import Depth
from .info import Info
from .time import Time
from .trades import Trades

@_dataclass
class MarketData(_MarketData, Candles, Depth, Info, Trades, Time):
  ...