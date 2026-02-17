from dataclasses import dataclass as _dataclass

from trading_sdk.core import SDK
from .data import MarketData, PerpMarketData
from .user import UserData, PerpUserData
from .trade import Trading

@_dataclass(frozen=True)
class Market(SDK):
  Data = MarketData
  User = UserData
  Trade = Trading
  data: MarketData
  user: UserData
  trade: Trading

@_dataclass(frozen=True)
class PerpMarket(Market):
  Data = PerpMarketData
  User = PerpUserData
  data: PerpMarketData
  user: PerpUserData