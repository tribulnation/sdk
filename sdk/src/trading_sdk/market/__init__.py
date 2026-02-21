from dataclasses import dataclass as _dataclass
import abc as _abc

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

  @property
  @_abc.abstractmethod
  def venue(self) -> str:
    """Venue identifier/name."""

  @property
  @_abc.abstractmethod
  def market_id(self) -> str:
    """Market identifier/name."""
    ...

  @property
  def id(self) -> str:
    return f'{self.venue}:{self.market_id}'

@_dataclass(frozen=True)
class PerpMarket(Market):
  Data = PerpMarketData
  User = PerpUserData
  data: PerpMarketData
  user: PerpUserData