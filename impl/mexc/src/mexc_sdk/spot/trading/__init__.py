from dataclasses import dataclass as _dataclass

from tribulnation.sdk.market import Trading as _Trading
from .cancel_order import CancelOrder
from .open_orders import OpenOrders
from .place_order import PlaceOrder
from .query_order import QueryOrder

@_dataclass
class Trading(_Trading, CancelOrder, OpenOrders, PlaceOrder, QueryOrder):
  ...