from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass

from tribulnation.sdk.market import Exchange, Settings, Ticker
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
  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch quotes and native 24-hour volumes for every spot symbol in one call.

    Args:
      markets: Symbols to keep. `None` keeps every symbol.
      settings: Accepted for interface compatibility and ignored because MEXC
        returns all ticker statistics in one request.
    """
    if markets is not None and not markets:
      return {}
    items = await self.client.spot.http.market.ticker_24hr(
      validate=self.shared.validate
    )
    if not isinstance(items, list):
      items = [items]
    wanted = None if markets is None else set(markets)
    result: dict[str, Ticker] = {}
    for item in items:
      symbol = item['symbol']
      if wanted is not None and symbol not in wanted:
        continue
      result[symbol] = Ticker(
        last=item['lastPrice'] if item['lastPrice'] > 0 else None,
        bid=item['bidPrice'] if item['bidPrice'] > 0 else None,
        ask=item['askPrice'] if item['askPrice'] > 0 else None,
        bid_qty=item['bidQty'] if item['bidQty'] > 0 else None,
        ask_qty=item['askQty'] if item['askQty'] > 0 else None,
        base_volume_24h=item['volume'],
        quote_volume_24h=item['quoteVolume'],
      )
    return result
