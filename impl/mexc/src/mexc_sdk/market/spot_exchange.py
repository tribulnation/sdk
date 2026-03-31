from typing_extensions import Sequence
from dataclasses import dataclass

from trading_sdk.market import Exchange
from .impl import ExchangeMixin
from .spot_market import SpotMarket

@dataclass(frozen=True, kw_only=True)
class SpotExchange(ExchangeMixin, Exchange):

  @property
  def venue_id(self) -> str:
    return 'mexc'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def markets(self) -> Sequence[str]:
    markets = await self.shared.load_markets()
    return list(markets.keys())

  async def market(self, market_id: str, /):
    markets = await self.shared.load_markets()
    info = markets[market_id]
    return SpotMarket(shared=self.shared, meta={'info': info})

