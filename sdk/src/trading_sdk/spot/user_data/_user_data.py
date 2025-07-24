from .balances import Balances
from .my_trades import MyTrades
from .open_orders import OpenOrders

class UserData(Balances, MyTrades, OpenOrders):
  ...