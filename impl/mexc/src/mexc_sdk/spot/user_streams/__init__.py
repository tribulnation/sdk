from dataclasses import dataclass as _dataclass

from .my_trades import MyTrades

@_dataclass
class UserStreams(MyTrades):
  ...