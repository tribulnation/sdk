from typing_extensions import Sequence, AsyncIterable, Literal
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from trading_sdk.market.user import Trades as _Trades

from mexc.core import timestamp as ts
from mexc.futures.user_data.my_trades import Side as HistorySide
from mexc.futures.streams.user.my_trades import Side as StreamSide
from mexc_sdk.core import PerpMixin, wrap_exceptions


def parse_side(side: HistorySide | StreamSide | int) -> Literal[1, -1]:
  match side:
    case HistorySide.open_long | HistorySide.close_short | StreamSide.open_long | StreamSide.close_short:
      return 1
    case HistorySide.open_short | HistorySide.close_long | StreamSide.open_short | StreamSide.close_long:
      return -1
  raise ValueError(f'Unknown side: {side}')


@dataclass(frozen=True)
class Trades(PerpMixin, _Trades):
  @wrap_exceptions
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Trades.Trade]]:
    page_size = 100
    page_num = 1

    contract_size = Decimal(self.info['contractSize'])

    while True:
      trades = await self.client.futures.my_trades(
        self.instrument,
        start=start,
        end=end,
        page_size=page_size,
        page_num=page_num,
      )
      yield [
        _Trades.Trade(
          id=str(t['id']),
          price=Decimal(t['price']),
          qty=Decimal(t['vol']) * contract_size * parse_side(t['side']),
          time=ts.parse(t['timestamp']).astimezone(),
          maker=not t['taker'],
          fee=_Trades.Trade.Fee(
            asset=t['feeCurrency'],
            amount=Decimal(t['fee']),
          ) if t.get('feeCurrency') and t.get('fee') else None,
          details=t,
        )
        for t in trades
      ]
      if len(trades) < page_size:
        break
      page_num += 1

  @wrap_exceptions
  async def stream(self) -> AsyncIterable[_Trades.Trade]:
    contract_size = Decimal(self.info['contractSize'])
    async for trade in self.my_trades_stream():
      yield _Trades.Trade(
        id=str(trade['id']),
        price=Decimal(trade['price']),
        qty=Decimal(trade['vol']) * contract_size * parse_side(trade['side']),
        time=ts.parse(trade['timestamp']),
        maker=not trade['taker'],
        fee=_Trades.Trade.Fee(
          amount=Decimal(trade['fee']),
          asset=trade['feeCurrency'],
        ) if trade.get('feeCurrency') and trade.get('fee') else None,
        details=trade,
      )
