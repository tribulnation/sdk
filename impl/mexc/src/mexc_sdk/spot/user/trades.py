from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.market.user import Trades as _Trades

from mexc.core import timestamp as ts
from mexc_sdk.core import SpotMixin, StreamsMixin, wrap_exceptions

@dataclass
class Trades(SpotMixin, StreamsMixin, _Trades):
  @wrap_exceptions
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Trades.Trade]]:
    async for trades in self.client.spot.my_trades_paged(self.instrument, start=start, end=end):
      chunk: list[_Trades.Trade] = []
      for t in trades:
        sign = 1 if t['isBuyer'] else -1
        chunk.append(_Trades.Trade(
          id=t['id'],
          price=Decimal(t['price']),
          qty=Decimal(t['qty']) * sign,
          time=ts.parse(t['time']).astimezone(),
          maker=t['isMaker'],
          fee=_Trades.Trade.Fee(
            asset=a,
            amount=Decimal(c),
          ) if (a := t.get('commissionAsset')) and (c := t.get('commission')) else None,
          details=t,
        ))
      yield chunk

  async def stream(self) -> AsyncIterable[_Trades.Trade]:
    async for trade in self.my_trades_stream():
      if trade.symbol == self.instrument:
        sign = 1 if trade.side == 'BUY' else -1
        yield _Trades.Trade(
          id=trade.tradeId,
          price=Decimal(trade.price),
          qty=Decimal(trade.base_qty) * sign,
          time=ts.parse(trade.time),
          maker=trade.maker,
          fee=_Trades.Trade.Fee(
            asset=trade.fee_currency,
            amount=Decimal(trade.fee_amount),
          ),
          details=trade,
        )