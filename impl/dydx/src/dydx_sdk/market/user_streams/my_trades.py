from typing_extensions import AsyncIterable
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.user_streams.my_trades import (
  MyTrades as _MyTrades, Trade
)

from dydx.core import timestamp as ts
from dydx_sdk.core import MarketMixin, SubaccountStreamMixin, wrap_exceptions

@dataclass
class MyTrades(MarketMixin, SubaccountStreamMixin, _MyTrades):
  @wrap_exceptions
  async def my_trades_stream(self) -> AsyncIterable[Trade]:
    async for log in self.subscribe_subaccounts():
      if (fills := log.get('fills')):
        for fill in fills:
          sign = 1 if fill['side'] == 'BUY' else -1
          yield Trade(
            id=fill['id'],
            price=Decimal(fill['price']),
            qty=Decimal(fill['size']) * sign,
            time=ts.parse(fill['createdAt']),
            maker=fill['liquidity'] == 'MAKER',
          )    