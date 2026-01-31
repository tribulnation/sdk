from dataclasses import dataclass as _dataclass, field as _field
from .market_data import MarketData
from .trading import Trading
from .user_data import UserData
from .market_streams import MarketStreams
from .user_streams import UserStreams

@_dataclass
class Spot(MarketData, Trading, UserData):
  market_streams: MarketStreams = _field(init=False)
  user_streams: UserStreams = _field(init=False)
  
  def __post_init__(self):
    self.market_streams = MarketStreams(client=self.client, instrument=self.instrument)
    self.user_streams = UserStreams(client=self.client, instrument=self.instrument)
