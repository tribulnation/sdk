from typing_extensions import Sequence, AsyncIterable
from dataclasses import dataclass
from functools import cache
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market.user_data.my_trades import MyTrades as _MyTrades, Trade, Side as SideTDK

from mexc.core import timestamp
from mexc.futures.user_data.my_trades import Side
from mexc_sdk.core import MarketMixin, wrap_exceptions

def parse_side(side: Side) -> SideTDK:
  match side:
    case Side.open_long | Side.close_short:
      return 'BUY'
    case Side.open_short | Side.close_long:
      return 'SELL'

@dataclass
class MyTrades(MarketMixin, _MyTrades):
  @wrap_exceptions
  async def _my_trades_impl(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    page_size = 100
    page_num = 1

    r = await self.client.futures.contract_info(self.instrument)
    contract_size = Decimal(r['contractSize'])

    while True:
      trades = await self.client.futures.my_trades(self.instrument, start=start, end=end, page_size=page_size, page_num=page_num)
      yield [
        Trade(
          id=str(t['id']),
          price=t['price'],
          qty=t['vol'] * contract_size,
          time=timestamp.parse(t['timestamp']),
          side=parse_side(t['side']),
          maker=not t['taker'],
          fee=Trade.Fee(
            asset=t['feeCurrency'],
            amount=t['fee'],
          ) if t['feeCurrency'] and t['fee'] else None,
        )
        for t in trades
      ]
      if len(trades) < page_size:
        break
      page_num += 1
    