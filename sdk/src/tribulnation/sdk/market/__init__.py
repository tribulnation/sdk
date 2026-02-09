from tribulnation.sdk.core import SDK
from .market_data import MarketData, PerpMarketData
from .market_streams import MarketStreams
from .trading import Trading
from .user_data import UserData, PerpUserData
from .user_streams import UserStreams

class Market(SDK):
  @property
  def market_data(self) -> MarketData: ...
  @property
  def market_streams(self) -> MarketStreams: ...
  @property
  def trading(self) -> Trading: ...
  @property
  def user_data(self) -> UserData: ...
  @property
  def user_streams(self) -> UserStreams: ...

class PerpMarket(Market, Protocol):
  @property
  def market_data(self) -> PerpMarketData: ...
  @property
  def user_data(self) -> PerpUserData: ...