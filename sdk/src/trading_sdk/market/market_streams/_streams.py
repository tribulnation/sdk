from typing_extensions import Protocol
from .depth import Depth

class MarketStreams(Depth, Protocol):
  ...