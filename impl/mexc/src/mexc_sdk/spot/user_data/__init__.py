from dataclasses import dataclass as _dataclass

from tribulnation.sdk.market import UserData as _UserData
from .my_trades import MyTrades
from .position import MyPosition
from .balances import Balances

@_dataclass
class UserData(_UserData, Balances, MyTrades, MyPosition):
  ...