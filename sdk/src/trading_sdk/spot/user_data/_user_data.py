from .balances import Balances
from .my_trades import MyTrades
from .open_orders import OpenOrders
from .query_orders import QueryOrders

class UserData(Balances, MyTrades, OpenOrders, QueryOrders):
  ...