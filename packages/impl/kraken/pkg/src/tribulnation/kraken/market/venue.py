"""Kraken Spot and public linear perpetual market data."""

from typing_extensions import Literal, Sequence, overload
from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from .impl import SharedMixin
from .spot_exchange import SpotExchange
from .perp_exchange import PerpExchange


@dataclass(frozen=True, kw_only=True)
class KrakenMarket(SharedMixin, TradingVenue):
  """Kraken implementation of `TradingVenue`.

  Spot retains its existing private capabilities; perpetuals expose public data
  through the independent Futures REST and Charts transports.
  """

  @property
  def venue_id(self) -> str:
    return 'kraken'

  @overload
  async def exchange(self, exchange_id: Literal['spot'], /) -> SpotExchange:
    """Resolve Spot with its concrete type."""
    ...

  @overload
  async def exchange(self, exchange_id: Literal['perp'], /) -> PerpExchange:
    """Resolve perpetuals with their concrete type."""
    ...

  @overload
  async def exchange(self, exchange_id: str, /) -> SpotExchange | PerpExchange:
    """Resolve a runtime exchange ID."""
    ...

  async def exchange(self, exchange_id: str, /) -> SpotExchange | PerpExchange:
    """Resolve the explicit Spot or qualified linear perpetual exchange."""
    if exchange_id == 'spot':
      return SpotExchange(shared=self.shared)
    if exchange_id == 'perp':
      return await self.perp_exchange(exchange_id)
    raise ValueError(f'Invalid Kraken exchange ID: {exchange_id}')

  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Resolve the public linear perpetual exchange by its explicit ID."""
    if exchange_id != 'perp':
      raise ValueError(f'Invalid Kraken perpetual exchange ID: {exchange_id}')
    return PerpExchange(shared=self.shared)

  async def exchanges(self) -> Sequence[TradingVenue.ExchangeDescription]:
    """List the public Spot and perpetual product identities."""
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'perp', 'type': 'perp', 'name': 'Linear perpetuals'},
    ]
