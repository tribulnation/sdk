from typing_extensions import AsyncIterable, Sequence
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.user_data.my_trades import (
  MyTrades as _MyTrades, Trade
)

from dydx.core import timestamp as ts
from dydx_sdk.core import MarketMixin, SubaccountMixin, wrap_exceptions

@dataclass
class MyTrades(MarketMixin, SubaccountMixin, _MyTrades):

  @wrap_exceptions
  async def _my_trades_impl(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:

    if start is not None:
      start = start.astimezone()
    if end is not None:
      end = end.astimezone()
      
    def within(t: datetime) -> bool:
      after = start is None or t >= start
      before = end is None or t <= end
      return after and before

    async for fills in self.indexer_data.get_fills_paged(
      self.address, subaccount=self.subaccount, ticker=self.market, end=end,
    ):
      trades: list[Trade] = []
      for f in fills:
        if within(t := ts.parse(f['createdAt'])) and f['market'] == self.market:
          sign = 1 if f['side'] == 'BUY' else -1
          trades.append(Trade(
            id=f['id'],
            price=Decimal(f['price']),
            qty=Decimal(f['size']) * sign,
            time=t,
            maker=f['liquidity'] == 'MAKER',
            fee=Trade.Fee(
              asset='USDC',
              amount=Decimal(f['fee']),
            )
          ))
      if trades:
        yield trades
