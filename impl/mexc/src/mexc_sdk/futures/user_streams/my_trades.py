from dataclasses import dataclass, field
from decimal import Decimal
from collections import defaultdict
import asyncio

from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market.user_streams.my_trades import MyTrades as _MyTrades, Trade

from mexc.core import timestamp as ts
from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class MyTrades(MarketMixin, _MyTrades):
  _queues: defaultdict[str, asyncio.Queue[Trade]] = field(default_factory=lambda: defaultdict(asyncio.Queue))
  _listener: asyncio.Task | None = None

  async def __aexit__(self, exc_type, exc_value, traceback):
    if self._listener is not None:
      self._listener.cancel()
      self._listener = None
    await super().__aexit__(exc_type, exc_value, traceback)

  @wrap_exceptions
  async def my_trades_stream(self):
    r = await self.client.futures.contract_info(self.instrument)
    if not 'data' in r:
      raise ApiError(r)
    
    contract_size = Decimal(r['data']['contractSize'])
    
    if self._listener is None:
      async def listener():
        async for trade in self.client.futures.streams.my_trades():
            qty = Decimal(trade['vol']) * contract_size
            t = Trade(
              id=trade['id'],
              price=Decimal(trade['price']),
              qty=qty,
              time=ts.parse(trade['timestamp']),
              side='BUY' if trade['side'] == 'BUY' else 'SELL',
              fee=Trade.Fee(
                amount=Decimal(trade['fee']),
                asset=trade['feeCurrency'],
              )
            )
            self._queues[trade['symbol']].put_nowait(t)
      self._listener = asyncio.create_task(listener())

    self._queues[self.instrument] # ensure the queue exists
    while True:
      # propagate exceptions raised in the listener
      t = asyncio.create_task(self._queues[self.instrument].get())
      await asyncio.wait([t, self._listener], return_when='FIRST_COMPLETED')
      if self._listener.done() and (exc := self._listener.exception()) is not None:
        raise exc
      yield await t
