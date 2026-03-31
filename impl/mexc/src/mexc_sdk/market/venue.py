from trading_sdk.market import TradingVenue

from .impl import SharedMixin
from .spot_exchange import SpotExchange

class MexcMarket(SharedMixin, TradingVenue):
  @property
  def venue_id(self) -> str:
    return 'mexc'

  async def exchange(self, exchange_id: str, /):
    if exchange_id != 'spot':
      raise ValueError(f'Invalid exchange ID: {exchange_id}. Only "spot" is supported.')
    return SpotExchange(self.shared)

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    return [{'id': 'spot', 'type': 'spot'}]