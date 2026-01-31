from dataclasses import dataclass as _dataclass

from .candles import Candles

@_dataclass
class MarketData(Candles):
  ...