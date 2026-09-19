"""Kraken public USD linear perpetual discovery, tickers and statistics."""

from dataclasses import dataclass
from typing_extensions import Collection, Mapping, Sequence

from tribulnation.sdk.market import (
  PerpExchange as BasePerpExchange,
  PerpStats,
  Settings,
  Ticker,
)
from typed_kraken.schemas import FuturesMarketTicker

from .impl import SharedMixin
from .impl.perp_data import is_market_ticker, parse_stats, parse_ticker
from .perp_market import PerpMarket


@dataclass(frozen=True, kw_only=True)
class PerpExchange(SharedMixin, BasePerpExchange):
  """Active non-tradfi linear perpetuals with USD quote and unit contract size."""

  @property
  def venue_id(self) -> str:
    """The Kraken platform owns every emitted native ID."""
    return 'kraken'

  @property
  def exchange_id(self) -> str:
    """Use the existing Catalogue perpetual identity."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """Discover contracts using explicit product metadata and current ticker status."""
    return list(await self.shared.load_perps())

  async def market(self, market_id: str, /) -> PerpMarket:
    """Construct only a listed, qualified native contract."""
    if market_id not in await self.shared.load_perps():
      raise ValueError(f'Unknown or unsupported Kraken linear perpetual: {market_id}')
    return PerpMarket(shared=self.shared, symbol=market_id)

  async def snapshots(
    self, markets: Collection[str] | None
  ) -> dict[str, FuturesMarketTicker]:
    """Fetch public snapshots restricted to the qualified instrument universe."""
    if markets is not None and not markets:
      return {}
    selected = set(await self.shared.load_perps())
    if markets is not None:
      selected.intersection_update(markets)
    if not selected:
      return {}
    response = await self.call_kraken(self.client.futures.tickers)
    return {
      row['symbol']: row
      for row in response['tickers']
      if is_market_ticker(row) and row['symbol'] in selected
    }

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Preserve native base-unit prices, sizes and 24-hour volume."""
    return {
      symbol: parse_ticker(row)
      for symbol, row in (await self.snapshots(markets)).items()
    }

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Expose published index, mark and open interest without derived funding estimates."""
    return {
      symbol: parse_stats(row)
      for symbol, row in (await self.snapshots(markets)).items()
    }
