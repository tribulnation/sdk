from typing_extensions import Sequence, AsyncIterable, Literal
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from collections import defaultdict
import asyncio

from tribulnation.sdk.market.user import Trades as _Trades

from mexc.core import timestamp as ts
from mexc.futures.user_data.my_trades import Side
from mexc_sdk.core import MarketMixin, wrap_exceptions


def parse_side(side: Side) -> Literal[1, -1]:
  match side:
    case Side.open_long | Side.close_short:
      return 1
    case Side.open_short | Side.close_long:
      return -1


@dataclass
class Trades(MarketMixin, _Trades):
  _queues: defaultdict[str, asyncio.Queue[_Trades.Trade]] = field(
    default_factory=lambda: defaultdict(asyncio.Queue)
  )
  _listener: asyncio.Task | None = None

  async def __aexit__(self, exc_type, exc_value, traceback):
    if self._listener is not None:
      self._listener.cancel()
      self._listener = None
    await super().__aexit__(exc_type, exc_value, traceback)

  @wrap_exceptions
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Trades.Trade]]:
    page_size = 100
    page_num = 1

    r = await self.client.futures.contract_info(self.instrument)
    contract_size = Decimal(r['contractSize'])

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
          time=ts.parse(t['timestamp']),
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

  async def stream(self) -> AsyncIterable[_Trades.Trade]:
    r = await self.client.futures.contract_info(self.instrument)
    contract_size = Decimal(r['contractSize'])

    if self._listener is None:
      async def listener():
        async for trade in self.client.futures.streams.my_trades():
          qty = Decimal(trade['vol']) * contract_size
          t = _Trades.Trade(
            id=str(trade['id']),
            price=Decimal(trade['price']),
            qty=qty if trade['side'] == 'BUY' else -qty,
            time=ts.parse(trade['timestamp']),
            maker=trade.get('maker', False),
            fee=_Trades.Trade.Fee(
              amount=Decimal(trade['fee']),
              asset=trade['feeCurrency'],
            ) if trade.get('feeCurrency') and trade.get('fee') else None,
            details=trade,
          )
          self._queues[trade['symbol']].put_nowait(t)
      self._listener = asyncio.create_task(listener())

    self._queues[self.instrument]
    while True:
      task = asyncio.create_task(self._queues[self.instrument].get())
      await asyncio.wait([task, self._listener], return_when='FIRST_COMPLETED')
      if self._listener.done() and (exc := self._listener.exception()) is not None:
        raise exc
      yield await task
