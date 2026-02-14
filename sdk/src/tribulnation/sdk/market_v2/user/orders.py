from typing_extensions import Sequence
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.core import SDK

class Orders(SDK):
  @dataclass
  class Order:
    id: str
    price: Decimal
    qty: Decimal
    """Signed quantity (netagive -> sell, positive -> buy)"""
    filled_qty: Decimal
    """Signed quantity (netagive -> sell, positive -> buy)"""
    active: bool
    """Whether the order is active in the market."""
    time: datetime

  @SDK.method
  @abstractmethod
  async def query(self, id: str) -> Order:
    """Fetch the state of the order with the given ID."""

  @SDK.method
  @abstractmethod
  async def open(self) -> Sequence[Order]:
    """Fetch your currently open orders."""
    