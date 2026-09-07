from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass

from tribulnation.sdk.market import (
  PerpExchange as _PerpExchange,
  PerpStats,
  Settings,
  Ticker,
)

from .impl import (
  SharedMixin,
  futures_permission_error,
  not_implemented,
  wrap_exceptions,
)
from .perp_market import PerpMarket


@dataclass(frozen=True, kw_only=True)
class PerpExchange(SharedMixin, _PerpExchange):
  """Binance's USD-M futures exchange."""

  @property
  def venue_id(self) -> str:
    return 'binance'

  @property
  def exchange_id(self) -> str:
    return 'usdm'

  @wrap_exceptions
  async def markets(self) -> Sequence[str]:
    info = await self.client.usdm_futures.http.market.exchange_info()
    return [
      s['symbol']
      for s in info['symbols']
      if s['contractType'] == 'PERPETUAL' and s['status'] == 'TRADING'
    ]

  async def market(self, market_id: str, /) -> PerpMarket:
    return PerpMarket(shared=self.shared, symbol=market_id)

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    raise not_implemented('tickers', self.id)

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    raise futures_permission_error('perp_stats', self.id)
