from dataclasses import dataclass

from .place_order import PlaceOrder
from .cancel_order import CancelOrder
from .query_order import QueryOrder

@dataclass
class Trading(PlaceOrder, CancelOrder, QueryOrder):
  ...