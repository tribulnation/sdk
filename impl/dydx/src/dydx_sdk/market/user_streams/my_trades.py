from typing_extensions import AsyncIterable
from dataclasses import dataclass, field
from decimal import Decimal

from tribulnation.sdk.market.user_streams.my_trades import (
  MyTrades as _MyTrades, Trade
)

from dydx.core import timestamp as ts
from dydx_sdk.core import MarketMixin, UserStreamsMixin, wrap_exceptions

@dataclass
class MyTrades(MarketMixin, UserStreamsMixin, _MyTrades):
  @wrap_exceptions
  async def my_trades_stream(self) -> AsyncIterable[Trade]:
    _, stream = await self.indexer_streams.subaccounts(self.address, subaccount=self.subaccount, validate=False)
    async for log in stream:
      print(log)
      if (fills := log.get('fills')):
        for fill in fills:
          if fill['ticker'] == self.market:
            yield Trade(
              id=fill['id'],
              price=Decimal(fill['price']),
              qty=Decimal(fill['size']),
              time=ts.parse(fill['createdAt']),
              side=fill['side'],
              maker=fill['liquidity'] == 'MAKER',
            )
