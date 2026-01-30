from typing_extensions import Protocol
from .market_data import MarketData, PerpMarketData
from .market_streams import MarketStreams
from .trading import Trading
from .user_data import UserData, PerpUserData
from .user_streams import UserStreams

class Market(MarketData, MarketStreams, Trading, UserData, UserStreams, Protocol):
  ...

class PerpMarket(Market, PerpMarketData, PerpUserData, Protocol):
  ...