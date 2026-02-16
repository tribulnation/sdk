from typing_extensions import Sequence, AsyncIterable
from dataclasses import dataclass
from datetime import datetime

from dydx.core import timestamp as ts
from tribulnation.sdk.market_v2.user import Funding as _Funding
from dydx_sdk.core import MarketMixin, IndexerDataMixin, SubaccountMixin, wrap_exceptions

@dataclass
class Funding(MarketMixin, IndexerDataMixin, SubaccountMixin, _Funding):
  @wrap_exceptions
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Funding.Payment]]:
    start = start.astimezone()
    end = end.astimezone()
      
    def within(t: datetime) -> bool:
      return start <= t <= end
    
    async for batch in self.indexer_data.get_funding_payments_paged(
      self.address, subaccount=self.subaccount, ticker=self.market, start=start
    ):
      fundings = [
        Funding.Payment(amount=f['payment'], time=t)
        for f in batch
          if within(t := ts.parse(f['createdAt']))
      ]
      if fundings:
        yield fundings