from typing_extensions import Protocol
from .depth import Depth, SpotDepth, PerpDepth, InversePerpDepth
from .instrument_info import InstrumentInfo, SpotInfo, PerpInfo, InversePerpInfo
from .time import Time
from .agg_trades import AggTrades, SpotAggTrades, PerpAggTrades, InversePerpAggTrades
from .candles import Candles, SpotCandles, PerpCandles, InversePerpCandles
from .funding_rate_history import FundingRateHistory, InversePerpFundingRateHistory

class MarketData(Depth, InstrumentInfo, Time, AggTrades, Candles, Protocol):
  ...

class SpotMarketData(MarketData, SpotDepth, SpotInfo, SpotAggTrades, SpotCandles, Protocol):
  ...

class PerpMarketData(MarketData, PerpDepth, PerpInfo, PerpAggTrades, PerpCandles, FundingRateHistory, Protocol):
  ...

class InversePerpMarketData(MarketData, InversePerpDepth, InversePerpInfo, InversePerpAggTrades, InversePerpCandles, InversePerpFundingRateHistory, Protocol):
  ...