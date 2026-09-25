"""Aster spot and perpetual exchange discovery."""

from dataclasses import dataclass
from functools import cached_property
from typing_extensions import Sequence
from tribulnation.sdk.market import TradingVenue
from ..core import SharedMixin
from .spot import SpotExchange
from .perp import PerpExchange


@dataclass(frozen=True, kw_only=True)
class AsterMarket(SharedMixin, TradingVenue):
  """One account exposing native spot and linear perpetual exchanges."""

  @cached_property
  def spot(self) -> SpotExchange:
    """The reusable spot exchange borrowing this account's state."""
    return SpotExchange(shared=self.shared)

  @cached_property
  def perp(self) -> PerpExchange:
    """The reusable perpetual exchange borrowing this account's state."""
    return PerpExchange(shared=self.shared)

  async def exchange(self, exchange_id: str, /) -> SpotExchange | PerpExchange:
    """Resolve only the two implemented product families."""
    if exchange_id == 'spot':
      return self.spot
    if exchange_id == 'perp':
      return self.perp
    raise ValueError(f'Unknown Aster exchange: {exchange_id}')

  async def exchanges(self) -> Sequence[TradingVenue.ExchangeDescription]:
    """List stable exchange IDs and product-family labels."""
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'perp', 'type': 'perp', 'name': 'Linear Perpetuals'},
    ]

  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Resolve the perpetual accessor to the same shared exchange instance."""
    if exchange_id != 'perp':
      raise ValueError(f'Unknown Aster perpetual exchange: {exchange_id}')
    return self.perp
