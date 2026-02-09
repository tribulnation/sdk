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
  def market_data(self) -> MarketData:
    return MarketData(client=self.client, instrument=self.instrument, validate=self.validate, recvWindow=self.recvWindow)

  @property
  def trading(self) -> Trading:
    return Trading(client=self.client, instrument=self.instrument, validate=self.validate, recvWindow=self.recvWindow)

  @property
  def user_data(self) -> UserData:
    return UserData(client=self.client, instrument=self.instrument, validate=self.validate, recvWindow=self.recvWindow)

  @property
  def market_streams(self) -> MarketStreams:
    return MarketStreams(client=self.client, instrument=self.instrument)

  @property
  def user_streams(self) -> UserStreams:
    return UserStreams(client=self.client, instrument=self.instrument)
