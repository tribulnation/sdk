from abc import ABC, abstractmethod
from typing_extensions import Mapping, TypeVar
from dataclasses import dataclass
from decimal import Decimal
import asyncio

S = TypeVar('S', bound=str, default=str)

@dataclass
class Balance:
  free: Decimal
  locked: Decimal

  @property
  def total(self) -> Decimal:
    return self.free + self.locked

class Balances(ABC):
  @abstractmethod
  async def balance(self, currency: S, /) -> Balance:
    """Get the balance of the given currency."""
    return (await self.balances(currency))[currency]

  @abstractmethod
  async def balances(self, *currencies: S) -> Mapping[S, Balance]:
    """Get the balances of the given currencies."""
    balances = await asyncio.gather(*(self.balance(currency) for currency in currencies))
    return {currency: balance for currency, balance in zip(currencies, balances)}