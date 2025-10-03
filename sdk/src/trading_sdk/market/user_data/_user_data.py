from typing_extensions import Protocol
from .balances import Balances
from .my_funding_history import PerpMyFundingHistory, InversePerpMyFundingHistory
from .my_trades import MyTrades, SpotMyTrades, PerpMyTrades, InversePerpMyTrades
from .open_orders import OpenOrders, SpotOpenOrders, PerpOpenOrders, InversePerpOpenOrders
from .positions import PerpPositions, InversePerpPositions
from .query_order import QueryOrder, SpotQueryOrder, PerpQueryOrder, InversePerpQueryOrder

class UserData(Balances, MyTrades, OpenOrders, QueryOrder, Protocol):
  ...

class SpotUserData(UserData, SpotMyTrades, SpotOpenOrders, SpotQueryOrder, Protocol):
  ...

class PerpUserData(UserData, PerpMyTrades, PerpOpenOrders, PerpQueryOrder, PerpMyFundingHistory, PerpPositions, Protocol):
  ...

class InversePerpUserData(UserData, InversePerpMyTrades, InversePerpOpenOrders, InversePerpQueryOrder, InversePerpMyFundingHistory, InversePerpPositions, Protocol):
  ...