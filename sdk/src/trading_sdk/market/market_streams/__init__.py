from typing_extensions import Protocol
from .depth import Depth
from .trades import Trades

class MarketStreams(Depth, Trades, Protocol):
  ...