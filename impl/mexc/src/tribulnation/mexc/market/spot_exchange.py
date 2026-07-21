from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market import Exchange, Ticker
from tribulnation.mexc.core.exc import wrap_exceptions
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

  @wrap_exceptions
  async def tickers(self, markets: Collection[str] | None = None) -> Mapping[str, Ticker]:
    """Fetch best bid/ask for every spot symbol in one call.

    Args:
      markets: Symbols to keep. `None` keeps every symbol.
    """
    items = await self.client.spot.market.book_ticker(validate=self.shared.validate)
    if not isinstance(items, list):
      items = [items]
    wanted = None if markets is None else set(markets)
    result: dict[str, Ticker] = {}
    for item in items:
      symbol = item.get('symbol')
      if symbol is None:
        continue
      if wanted is not None and symbol not in wanted:
        continue
      result[symbol] = Ticker(
        bid=Decimal(p) if (p := item.get('bidPrice')) else None,
        ask=Decimal(p) if (p := item.get('askPrice')) else None,
        bid_qty=Decimal(q) if (q := item.get('bidQty')) else None,
        ask_qty=Decimal(q) if (q := item.get('askQty')) else None,
      )
    return result

