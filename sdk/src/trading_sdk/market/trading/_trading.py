from typing_extensions import Protocol
from .edit_order import EditOrder, SpotEditOrder, PerpEditOrder, InversePerpEditOrder
from .cancel_order import CancelOrder, SpotCancelOrder, PerpCancelOrder, InversePerpCancelOrder
from .place_order import PlaceOrder, SpotPlaceOrder, PerpPlaceOrder, InversePerpPlaceOrder

class Trading(CancelOrder, EditOrder, PlaceOrder, Protocol):
  ...

class SpotTrading(Trading, SpotEditOrder, SpotCancelOrder, SpotPlaceOrder, InversePerpEditOrder, InversePerpCancelOrder, Protocol):
  ...

class PerpTrading(Trading, PerpEditOrder, PerpCancelOrder, PerpPlaceOrder, InversePerpEditOrder, InversePerpCancelOrder, Protocol):
  ...

class InversePerpTrading(Trading, InversePerpEditOrder, InversePerpCancelOrder, InversePerpPlaceOrder, Protocol):
  ...