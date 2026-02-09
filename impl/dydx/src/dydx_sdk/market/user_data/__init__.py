from dataclasses import dataclass

from .my_funding_history import MyFundingHistory
from .my_trades import MyTrades
from .my_position import MyPosition

@dataclass
class UserData(MyFundingHistory, MyTrades, MyPosition):
  ...