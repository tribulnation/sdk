from .balance import Balances
from .my_funding_history import MyFundingHistory
from .my_trades import MyTrades
from .my_position import MyPosition

class UserData(Balances, MyTrades, MyPosition):
  ...
class PerpUserData(UserData, MyFundingHistory):
  ...