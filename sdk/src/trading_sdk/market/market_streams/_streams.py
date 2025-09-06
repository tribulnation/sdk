from typing_extensions import Protocol
from .depth import Depth, SpotDepth, PerpDepth, InversePerpDepth

class MarketStreams(Depth, Protocol):
  ...

class SpotMarketStreams(MarketStreams, SpotDepth, Protocol):
  ...

class PerpMarketStreams(MarketStreams, PerpDepth, Protocol):
  ...

class InversePerpMarketStreams(MarketStreams, InversePerpDepth, Protocol):
  ...