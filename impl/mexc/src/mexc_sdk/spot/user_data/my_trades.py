from typing_extensions import Sequence, AsyncIterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.market.user_data.my_trades import MyTrades as _MyTrades, Trade

from mexc.core import timestamp
from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class MyTrades(MarketMixin, _MyTrades):
  @wrap_exceptions
  async def _my_trades_impl(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Trade]]:
    async for trades in self.client.spot.my_trades_paged(self.instrument, start=start, end=end):
      yield [
        Trade(
          id=t['id'],
          price=Decimal(t['price']),
          qty=Decimal(t['qty']),
          time=timestamp.parse(t['time']).astimezone(),
          side='BUY' if t['isBuyer'] else 'SELL',
          maker=t['isMaker'],
          fee=Trade.Fee(
            asset=a,
            amount=Decimal(c),
          ) if (a := t.get('commissionAsset')) and (c := t.get('commission')) else None,
        )
        for t in trades
      ]
