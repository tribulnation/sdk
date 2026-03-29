from typing_extensions import AsyncIterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from trading_sdk.market import FundingRate, FundingPayment

from dydx_sdk.core import wrap_exceptions
from .mixin import MarketMixin

@wrap_exceptions
async def next_funding(self: MarketMixin) -> FundingRate:
  market = await self.indexer.data.get_market(self.market)
  now = datetime.now().astimezone()
  next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
  return FundingRate(
    rate=Decimal(market['nextFundingRate']),
    time=next_hour,
  )

@wrap_exceptions
async def funding_history(self: MarketMixin, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingRate]]:
  start = start.astimezone()
  end = end.astimezone()
  paging = self.indexer.data.get_historical_funding_paged(self.market, effective_before_or_at=end)
  state = paging.init
  while state is not None:
    page, state = await self.call(lambda: paging.next(state))
    rates = [
      FundingRate(rate=Decimal(item['rate']), time=time)
      for item in page
      if (time := item['effectiveAt']) >= start
    ]
    if rates:
      yield rates
    else:
      break

@wrap_exceptions
async def funding_payments(self: MarketMixin, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingPayment]]:
  start = start.astimezone()
  end = end.astimezone()
  paging = self.indexer.data.get_funding_payments_paged(
    address=await self.address,
    subaccount=self.subaccount,
    ticker=self.market,
    after_or_at=start,
  )
  state = paging.init
  while state is not None:
    batch, state = await self.call(lambda: paging.next(state))
    payments = [
      FundingPayment(amount=Decimal(item['payment']), time=item['createdAt'])
      for item in batch
      if start <= item['createdAt'] <= end
    ]
    if payments:
      yield payments