from dataclasses import dataclass as _dataclass

from .my_trades import MyTrades
from .balances import Balances

@_dataclass
class UserData(MyTrades, Balances):
  ...