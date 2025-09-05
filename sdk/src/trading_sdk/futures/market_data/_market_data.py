from typing_extensions import Protocol

from trading_sdk.market import MarketData as _MarketData
from .funding_rate_history import FundingRateHistory

class MarketData(_MarketData, FundingRateHistory, Protocol):
  ...