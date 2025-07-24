from .cancel_order import CancelOrder
from .place_order import PlaceOrder
from .query_order import QueryOrder

class Trading(CancelOrder, PlaceOrder, QueryOrder):
  ...