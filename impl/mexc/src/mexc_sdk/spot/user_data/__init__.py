from dataclasses import dataclass as _dataclass

from .my_trades import MyTrades
from .open_orders import OpenOrders
from .query_order import QueryOrder
from .balances import Balances

@_dataclass
class UserData(MyTrades, OpenOrders, QueryOrder, Balances):
  ...