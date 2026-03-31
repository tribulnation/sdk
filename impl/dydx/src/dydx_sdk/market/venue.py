from dataclasses import dataclass

from trading_sdk import TradingVenue

from .impl import ExchangeMixin
from .exchange import Exchange

def parse_market_id(market_id: str) -> tuple[str, int]:
  if ':' in market_id:
    base, subaccount = market_id.split(':', 1)
    return base, int(subaccount)
  return market_id, 0

@dataclass(frozen=True)
class DydxMarket(ExchangeMixin, TradingVenue):

  @property
  def venue_id(self) -> str:
    return 'dydx'

  async def exchange(self, exchange_id: str, /) -> Exchange:
    if exchange_id != 'perp':
      raise ValueError(f'Invalid exchange ID: {exchange_id}. Only "perp" is supported.')
    return Exchange(shared=self.shared)

  async def perp_exchange(self, exchange_id: str, /):
    return await self.exchange(exchange_id)

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    return [{'id': 'perp', 'type': 'perp'}]