from tribulnation.sdk.market import TradingVenue

from .impl import SharedMixin
from .spot_exchange import SpotExchange
from .perp_exchange import PerpExchange


class MexcMarket(SharedMixin, TradingVenue):
  @property
  def venue_id(self) -> str:
    return 'mexc'

  async def exchange(self, exchange_id: str, /):
    """Resolve spot or the public linear perpetual exchange."""
    if exchange_id == 'spot':
      return SpotExchange(self.shared)
    return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Resolve the perpetual exchange without enabling private futures access."""
    if exchange_id != 'perp':
      raise ValueError(
        f'Invalid MEXC exchange ID: {exchange_id!r}; expected spot or perp'
      )
    return PerpExchange(self.shared)

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'perp', 'type': 'perp', 'name': 'Linear Perpetuals'},
    ]
