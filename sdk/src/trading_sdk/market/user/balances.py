from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.core import SDK

  
class Balances(SDK):
  @dataclass
  class Balance:
    free: Decimal = Decimal(0)
    locked: Decimal = Decimal(0)

    @property
    def total(self) -> Decimal:
      return self.free + self.locked
      
  @SDK.method
  @abstractmethod
  async def quote(self) -> Balance:
    """Fetch the quote/collateral currency balance."""