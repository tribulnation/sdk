from dataclasses import dataclass as _dataclass

from tribulnation.sdk.core import SDK
from .data import MarketData, PerpMarketData
from .user import UserData, PerpUserData
from .trade import Trading

@_dataclass(frozen=True)
class Market(SDK):
  data: MarketData
  user: UserData
  trade: Trading
  
@_dataclass(frozen=True)
class PerpMarket(Market):
  data: PerpMarketData
  user: PerpUserData