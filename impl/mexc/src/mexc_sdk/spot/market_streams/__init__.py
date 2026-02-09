from dataclasses import dataclass as _dataclass

from .depth import Depth
from .trades import Trades

@_dataclass
class MarketStreams(Depth, Trades):
  ...