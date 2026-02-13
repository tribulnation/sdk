from dataclasses import dataclass as _dataclass

from tribulnation.sdk.market import MarketStreams as _MarketStreams
from .depth import Depth
from .trades import Trades

@_dataclass
class MarketStreams(_MarketStreams, Depth, Trades):
  ...