from dataclasses import dataclass

from tribulnation.sdk.market import PerpUserData
from .my_funding_history import MyFundingHistory
from .my_trades import MyTrades
from .my_position import MyPosition

@dataclass
class UserData(PerpUserData, MyFundingHistory, MyTrades, MyPosition):
  
  async def balance(self, currency: str, /):
    raise NotImplementedError