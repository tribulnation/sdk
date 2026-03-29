from dataclasses import dataclass

from trading_sdk import PerpExchange

from .impl import ExchangeMixin
from .market import Market

def parse_market_id(market_id: str) -> tuple[str, int]:
  if ':' in market_id:
    base, subaccount = market_id.split(':', 1)
    return base, int(subaccount)
  return market_id, 0

@dataclass(frozen=True)
class Exchange(ExchangeMixin, PerpExchange):

  @property
  def exchange_id(self) -> str:
    return 'perp'

  @property
  def venue_id(self) -> str:
    return 'dydx'

  async def markets(self):
    markets = await self.shared.load_markets()
    return list(markets)

  async def market(self, market_id: str, /):
    """Fetch a market by ID.
    
    - `market_id`: `<BASE>-USD` or `<BASE>-USD:<subaccount>`
    """
    ticker, subaccount = parse_market_id(market_id)
    markets = await self.shared.load_markets()
    return Market(shared=self.shared, perpetual_market=markets[ticker], subaccount=subaccount)