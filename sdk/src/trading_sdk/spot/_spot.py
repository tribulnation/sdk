from typing_extensions import Protocol
from .market_data import MarketData
from .user_data import UserData
from .trading import Trading

class Spot(MarketData, UserData, Trading, Protocol):
  ...