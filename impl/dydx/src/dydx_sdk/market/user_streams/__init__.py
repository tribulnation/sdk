from dataclasses import dataclass

from tribulnation.sdk.market import UserStreams as _UserStreams
from .my_trades import MyTrades

@dataclass
class UserStreams(_UserStreams, MyTrades):
  ...