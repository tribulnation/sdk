from typing_extensions import Sequence, AsyncIterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from dydx.core import timestamp as ts
from trading_sdk.market.user import Trades as _Trades
from dydx_sdk.core import MarketMixin, wrap_exceptions

@dataclass(frozen=True)
class Trades(MarketMixin, _Trades):
  @wrap_exceptions
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Trades.Trade]]:
    if start is not None:
      start = start.astimezone()
    if end is not None:
      end = end.astimezone()
      
    def within(t: datetime) -> bool:
      after = start is None or t >= start
      before = end is None or t <= end
      return after and before

    async for fills in self.indexer.data.get_fills_paged(
      self.address, subaccount=self.subaccount, end=end,
      market=self.market, market_type='PERPETUAL'
    ):
      trades: list[_Trades.Trade] = []
      for f in fills:
        if within(t := ts.parse(f['createdAt'])) and f['market'] == self.market:
          sign = 1 if f['side'] == 'BUY' else -1
          trades.append(_Trades.Trade(
            id=f['id'],
            price=f['price'],
            qty=f['size'] * sign,
            time=t,
            maker=f['liquidity'] == 'MAKER',
            fee=_Trades.Trade.Fee(
              asset='USDC',
              amount=f['fee'],
            )
          ))
      if trades:
        yield trades

  @wrap_exceptions
  async def stream(self) -> AsyncIterable[_Trades.Trade]:
    async for log in self.subscribe_subaccounts():
      if (fills := log.get('fills')):
        for fill in fills:
          sign = 1 if fill['side'] == 'BUY' else -1
          yield _Trades.Trade(
            id=fill['id'],
            price=Decimal(fill['price']),
            qty=Decimal(fill['size']) * sign,
            time=ts.parse(fill['createdAt']),
            maker=fill['liquidity'] == 'MAKER',
            fee=None,
            details=fill,
          )    