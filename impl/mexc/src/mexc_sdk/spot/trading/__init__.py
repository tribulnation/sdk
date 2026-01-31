from dataclasses import dataclass as _dataclass

from .place_order import PlaceOrder
from .cancel_order import CancelOrder

@_dataclass
class Trading(PlaceOrder, CancelOrder):
  ...