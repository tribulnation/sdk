from typing_extensions import Protocol
from .my_trades import MyTrades, SpotMyTrades, PerpMyTrades, InversePerpMyTrades

class UserStreams(MyTrades, Protocol):
  ...

class SpotUserStreams(UserStreams, SpotMyTrades, Protocol):
  ...

class PerpUserStreams(UserStreams, PerpMyTrades, Protocol):
  ...

class InversePerpUserStreams(UserStreams, InversePerpMyTrades, Protocol):
  ...