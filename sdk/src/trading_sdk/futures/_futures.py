from typing_extensions import Protocol

from trading_sdk.market import Market
from .market_data import MarketData
from .user_data import UserData

class Futures(Market, MarketData, UserData, Protocol):
  ...