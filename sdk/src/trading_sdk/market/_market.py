from typing_extensions import Protocol
from .market_data import MarketData, SpotMarketData, PerpMarketData
from .user_data import UserData, SpotUserData, PerpUserData
from .trading import Trading, SpotTrading, PerpTrading

class Market(MarketData, UserData, Trading, Protocol):
  ...

class SpotMarket(Market, SpotMarketData, SpotUserData, SpotTrading, Protocol):
  ...

class PerpMarket(Market, PerpMarketData, PerpUserData, PerpTrading, Protocol):
  ...