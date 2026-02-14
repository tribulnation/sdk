from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.core import SDK

  
class Balances(SDK):
  @dataclass
  class Balance:
    free: Decimal
    locked: Decimal

    @property
    def total(self) -> Decimal:
      return self.free + self.locked
      
  @SDK.method
  @abstractmethod
  async def quote(self) -> Balance:
    """Fetch the quote/collateral currency balance."""