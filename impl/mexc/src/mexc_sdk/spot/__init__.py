from dataclasses import dataclass as _dataclass, field as _field

from tribulnation.sdk.market import Market

from mexc_sdk.core import MarketMixin
from .market_data import MarketData
from .trading import Trading
from .user_data import UserData
from .market_streams import MarketStreams
from .user_streams import UserStreams

@_dataclass
class Spot(Market, MarketMixin):

  @property
  def id(self) -> str:
    return f'mexc:{self.instrument}'

  def __post_init__(self):
    self._market_data = MarketData(client=self.client, instrument=self.instrument, validate=self.validate, recvWindow=self.recvWindow)
    self._trading = Trading(client=self.client, instrument=self.instrument, validate=self.validate, recvWindow=self.recvWindow)
    self._user_data = UserData(client=self.client, instrument=self.instrument, validate=self.validate, recvWindow=self.recvWindow)
    self._market_streams = MarketStreams(client=self.client, instrument=self.instrument)
    self._user_streams = UserStreams(client=self.client, instrument=self.instrument)

  @property
  def market_data(self) -> MarketData:
    return self._market_data

  @property
  def trading(self) -> Trading:
    return self._trading

  @property
  def user_data(self) -> UserData:
    return self._user_data

  @property
  def market_streams(self) -> MarketStreams:
    return self._market_streams

  @property
  def user_streams(self) -> UserStreams:
    return self._user_streams
