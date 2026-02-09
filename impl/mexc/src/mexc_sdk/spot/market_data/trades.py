from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.core import SDK
from tribulnation.sdk.market.market_data.trades import Trades as _Trades, Trade

from mexc.core import timestamp as ts
from mexc.spot.market_data.candles import Interval
from mexc_sdk.core import MarketMixin, wrap_exceptions


@dataclass
class Trades(_Trades, MarketMixin):
  trades_paging_interval: timedelta = field(default_factory=lambda: timedelta(hours=1), kw_only=True)
  """Interval to page trades."""
  trades_max_back: timedelta = field(default_factory=lambda: timedelta(days=2), kw_only=True)
  """Maximum back to fetch trades supported by the API."""

  @SDK.method
  @wrap_exceptions
  async def _trades_page(self, start: datetime, end: datetime) -> Sequence[Trade]:
    trades = await self.client.spot.agg_trades(self.instrument, start=start, end=end)
    return [Trade(
      id=t['a'] or t['f'] or f'{t["T"]}_{t["p"]}_{t["q"]}',
      price=Decimal(t['p']),
      qty=Decimal(t['q']),
      time=ts.parse(t['T']),
      maker='buyer' if t['m'] else 'seller',
    ) for t in trades]

  
  async def _trades_impl(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    interval = self.trades_paging_interval
    start = max(start, datetime.now() - self.trades_max_back)
    while start < end:
      trades = await self._trades_page(start, start+interval)
      if trades:
        yield trades
      start += interval