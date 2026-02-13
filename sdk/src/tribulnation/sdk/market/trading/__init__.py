from .cancel_order import CancelOrder
from .open_orders import OpenOrders
from .place_order import PlaceOrder
from .query_order import QueryOrder

class Trading(CancelOrder, OpenOrders, PlaceOrder, QueryOrder):
  ...