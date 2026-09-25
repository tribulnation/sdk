"""The Aster trading venue: spot and linear perpetual exchanges."""

from dataclasses import dataclass
from functools import cached_property
from typing_extensions import Sequence
from tribulnation.sdk.market import TradingVenue
from ..core import Public
from .exchanges import PerpExchange, SpotExchange


@dataclass(frozen=True, kw_only=True)
class AsterMarket(Public, TradingVenue):
  """One Aster account's spot and perpetual exchanges, sharing its client."""

  @cached_property
  def spot(self) -> SpotExchange:
    """The spot exchange."""
    return SpotExchange(shared=self.shared)

  @cached_property
  def perp(self) -> PerpExchange:
    """The perpetual exchange."""
    return PerpExchange(shared=self.shared)

  async def exchanges(self) -> Sequence[TradingVenue.ExchangeDescription]:
    """List the spot and perpetual exchanges."""
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'perp', 'type': 'perp', 'name': 'Linear Perpetuals'},
    ]

  async def exchange(self, exchange_id: str, /) -> SpotExchange | PerpExchange:
    """Resolve `spot` or `perp`."""
    if exchange_id == 'spot':
      return self.spot
    if exchange_id == 'perp':
      return self.perp
    raise ValueError(f'Unknown Aster exchange: {exchange_id}')

  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Resolve `perp`."""
    if exchange_id != 'perp':
      raise ValueError(f'Unknown Aster perpetual exchange: {exchange_id}')
    return self.perp
