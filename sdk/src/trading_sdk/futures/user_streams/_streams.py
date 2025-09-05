from typing_extensions import Protocol
from .my_trades import MyTrades

class UserStreams(MyTrades, Protocol):
  ...