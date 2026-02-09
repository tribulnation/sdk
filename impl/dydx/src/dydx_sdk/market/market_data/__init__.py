from dataclasses import dataclass

from .candles import Candles
from .depth import Depth

@dataclass
class MarketData(Candles, Depth):
  ...