from dataclasses import dataclass as _dataclass

from .candles import Candles
from .depth import Depth
from .info import Info
from .time import Time
from .trades import Trades

@_dataclass
class MarketData(Candles, Depth, Info, Time, Trades):
  ...