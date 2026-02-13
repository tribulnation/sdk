from dataclasses import dataclass

from tribulnation.sdk.market import MarketStreams as _MarketStreams

@dataclass
class MarketStreams(_MarketStreams):
  async def depth_stream(self, *, limit: int | None = None):
    raise NotImplementedError
    yield

  async def trades_stream(self):
    raise NotImplementedError
    yield
