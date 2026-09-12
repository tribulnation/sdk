from dataclasses import dataclass

from tribulnation.sdk.market import TradingVenue

from .impl import SharedMixin
from .spot_exchange import SpotExchange
from .perp_exchange import PerpExchange


@dataclass(frozen=True)
class BinanceMarket(SharedMixin, TradingVenue):
  """Binance trading venue: `spot` and `usdm` (USD-M futures) exchanges."""

  @property
  def venue_id(self) -> str:
    return 'binance'

  async def exchange(self, exchange_id: str, /):
    if exchange_id == 'spot':
      return SpotExchange(shared=self.shared)
    return await self.perp_exchange(exchange_id)

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    return [
      {'id': 'spot', 'type': 'spot', 'name': 'Spot'},
      {'id': 'usdm', 'type': 'perp', 'name': 'USD-M Futures'},
    ]

  async def perp_exchange(self, exchange_id: str, /):
    if exchange_id != 'usdm':
      raise ValueError(
        f'Invalid perp exchange ID: {exchange_id!r}. Only "usdm" (USD-M futures) is supported.'
      )
    return PerpExchange(shared=self.shared)
