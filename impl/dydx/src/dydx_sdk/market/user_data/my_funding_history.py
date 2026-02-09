from typing_extensions import AsyncIterable, Sequence
from datetime import datetime
from dataclasses import dataclass

from tribulnation.sdk.market.user_data.my_funding_history import (
  MyFundingHistory as _MyFundingHistory, Funding
)

from dydx.core import timestamp as ts
from dydx_sdk.core import MarketMixin, UserDataMixin, wrap_exceptions

@dataclass
class MyFundingHistory(MarketMixin, UserDataMixin, _MyFundingHistory):

  @wrap_exceptions
  async def _my_funding_history_impl(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Funding]]:

    start = start.astimezone()
    end = end.astimezone()
      
    def within(t: datetime) -> bool:
      after = start is None or t >= start
      before = end is None or t <= end
      return after and before
    
    async for batch in self.indexer_data.get_funding_payments_paged(
      self.address, subaccount=self.subaccount, ticker=self.market, start=start
    ):
      fundings = [
        Funding(
          funding=f['payment'],
          time=t,
          side=f['side'],
          currency='USDC',
          rate=f['rate']
        )
        for f in batch
          if within(t := ts.parse(f['createdAt']))
      ]
      if fundings:
        yield fundings