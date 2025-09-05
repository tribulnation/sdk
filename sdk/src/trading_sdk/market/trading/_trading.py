from typing_extensions import Protocol
from .edit_order import EditOrder
from .cancel_order import CancelOrder
from .place_orders import PlaceOrders

class Trading(CancelOrder, EditOrder, PlaceOrders, Protocol):
  ...