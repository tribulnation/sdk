from dataclasses import dataclass as _dataclass

from .balances import Balances
from .my_funding_history import MyFundingHistory
from .my_trades import MyTrades
from .positions import MyPosition

@_dataclass
class UserData(Balances, MyFundingHistory, MyTrades, MyPosition):
  ...