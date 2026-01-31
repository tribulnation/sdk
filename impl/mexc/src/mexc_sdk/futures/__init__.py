from dataclasses import dataclass as _dataclass, field as _field

from .market_data import MarketData
from .user_data import UserData
from .user_streams import UserStreams

@_dataclass
class Futures(MarketData, UserData):
  user_streams: UserStreams = _field(init=False)
  
  def __post_init__(self):
    self.user_streams = UserStreams(client=self.client)