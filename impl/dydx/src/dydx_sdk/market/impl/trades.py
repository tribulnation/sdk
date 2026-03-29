from typing_extensions import AsyncIterable, Sequence
from datetime import datetime
from decimal import Decimal

from trading_sdk.market import Trade
from trading_sdk.core import Stream

from dydx_sdk.core import wrap_exceptions
from .mixin import MarketMixin

@wrap_exceptions
async def trades_history(self: MarketMixin, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
  start = start.astimezone()
  end = end.astimezone()

  def within(time: datetime) -> bool:
    return start <= time <= end

  paging = self.indexer.data.get_fills_paged(
    address=await self.address,
    subaccount=self.subaccount,
    created_before_or_at=end,
    market=self.market,
    market_type='PERPETUAL',
  )
  state = paging.init
  while state is not None:
    fills, state = await paging.next(state)
    trades: list[Trade] = []
    for fill in fills:
      if fill['market'] != self.market or not within(fill['createdAt']):
        continue
      sign = 1 if fill['side'] == 'BUY' else -1
      trades.append(Trade(
        id=fill['id'],
        price=Decimal(fill['price']),
        qty=Decimal(fill['size']) * sign,
        time=fill['createdAt'],
        maker=fill['liquidity'] == 'MAKER',
        fee=Trade.Fee(asset='USDC', amount=Decimal(fill['fee'])),
        details=fill,
      ))
    if trades:
      yield trades


@wrap_exceptions
async def trades_stream(self: MarketMixin) -> Stream[Trade]:
  subaccounts = await self.subscribe_subaccount(self.subaccount)

  async def stream():
    async for log in subaccounts:
      fills = log.get('fills')
      if fills is None:
        continue
      for fill in fills:
        if fill['ticker'] != self.market:
          continue
        sign = 1 if fill['side'] == 'BUY' else -1
        yield Trade(
          id=fill['id'],
          price=Decimal(fill['price']),
          qty=Decimal(fill['size']) * sign,
          time=fill['createdAt'],
          maker=fill['liquidity'] == 'MAKER',
          fee=None,
          details=fill,
        )

  return Stream(stream(), subaccounts.unsubscribe)