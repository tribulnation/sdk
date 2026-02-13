from dataclasses import dataclass as _dataclass

from tribulnation.sdk.market import UserStreams as _UserStreams
from .my_trades import MyTrades

@_dataclass
class UserStreams(_UserStreams, MyTrades):
  ...