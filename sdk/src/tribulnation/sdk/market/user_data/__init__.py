from typing_extensions import Protocol
from .balances import Balances
from .my_funding_history import MyFundingHistory
from .my_trades import MyTrades
from .positions import MyPosition

class UserData(Balances, MyTrades, Protocol):
  ...
class PerpUserData(UserData, MyFundingHistory, MyPosition, Protocol):
  ...