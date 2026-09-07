from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass

from tribulnation.sdk.market import Exchange, Market, Settings, Ticker

from .impl import SharedMixin, not_implemented
from .spot_market import SpotMarket


@dataclass(frozen=True, kw_only=True)
class SpotExchange(SharedMixin, Exchange):
  """Binance's spot exchange."""

  @property
  def venue_id(self) -> str:
    return 'binance'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def markets(self) -> Sequence[str]:
    symbols = await self.shared.load_spot_symbols()
    return list(symbols.keys())

  async def market(self, market_id: str, /) -> Market:
    symbols = await self.shared.load_spot_symbols()
    if market_id not in symbols:
      raise ValueError(f'Unknown Binance spot market: {market_id!r}')
    return SpotMarket(shared=self.shared, symbol=market_id)

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    raise not_implemented('tickers', self.id)
