from dataclasses import dataclass as _dataclass

from .candles import Candles
from .depth import Depth
from .instrument_info import InstrumentInfo
from .time import Time
from .trades import Trades

@_dataclass
class MarketData(Candles, Depth, InstrumentInfo, Time, Trades):
  ...