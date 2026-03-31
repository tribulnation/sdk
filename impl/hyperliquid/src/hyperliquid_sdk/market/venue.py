from dataclasses import dataclass

from trading_sdk import TradingVenue

from .impl import SharedMixin
from .perps_exchange import PerpExchange
from .spot_exchange import SpotExchange

@dataclass(frozen=True)
class HyperliquidMarket(SharedMixin, TradingVenue):
  @property
  def venue_id(self) -> str:
    return 'hyperliquid'

  async def exchange(self, exchange_id: str, /):
    if exchange_id == 'spot':
      return SpotExchange(shared=self.shared)
    else:
      return await self.perp_exchange(exchange_id)

  async def perp_exchange(self, exchange_id: str, /):
    return await PerpExchange.fetch(self.shared, dex=exchange_id or None)

  async def market(self, exchange_market_id: str, /):
    exchange_id, market_id = exchange_market_id.split(':', 1)
    exchange = await self.exchange(exchange_id)
    return await exchange.market(market_id)

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    out: list[TradingVenue.ExchangeDescription] = [
      {'id': 'spot', 'type': 'spot'},
      {'id': '', 'type': 'perp'},
    ]
    dexs = await self.shared.load_perp_dexs()
    for dex in dexs.values():
      if dex is not None:
        out.append({'id': dex['name'], 'type': 'perp'})
    return out