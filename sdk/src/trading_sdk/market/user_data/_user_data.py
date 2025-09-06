from typing_extensions import Protocol
from .balances import Balances
from .my_trades import MyTrades, SpotMyTrades, PerpMyTrades, InversePerpMyTrades
from .open_orders import OpenOrders, SpotOpenOrders, PerpOpenOrders, InversePerpOpenOrders
from .query_order import QueryOrder, SpotQueryOrder, PerpQueryOrder, InversePerpQueryOrder

class UserData(Balances, MyTrades, OpenOrders, QueryOrder, Protocol):
  ...

class SpotUserData(UserData, SpotMyTrades, SpotOpenOrders, SpotQueryOrder, Protocol):
  ...

class PerpUserData(UserData, PerpMyTrades, PerpOpenOrders, PerpQueryOrder, Protocol):
  ...

class InversePerpUserData(UserData, InversePerpMyTrades, InversePerpOpenOrders, InversePerpQueryOrder, Protocol):
  ...