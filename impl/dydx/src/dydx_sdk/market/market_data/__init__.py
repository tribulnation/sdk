from dataclasses import dataclass

from tribulnation.sdk.market import PerpMarketData
from .candles import Candles
from .depth import Depth
from .funding_rate_history import FundingRateHistory

@dataclass
class MarketData(PerpMarketData, Candles, Depth, FundingRateHistory):
  async def _trades_impl(self, start, end):
    raise NotImplementedError
    yield

  async def time(self):
    raise NotImplementedError

  async def info(self):
    raise NotImplementedError


