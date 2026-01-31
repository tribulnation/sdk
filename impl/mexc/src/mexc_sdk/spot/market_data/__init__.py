from dataclasses import dataclass as _dataclass

from .depth import Depth
from .instrument_info import InstrumentInfo
from .candles import Candles

@_dataclass
class MarketData(Depth, InstrumentInfo, Candles):
  ...