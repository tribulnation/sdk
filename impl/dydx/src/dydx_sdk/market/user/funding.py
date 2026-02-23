from typing_extensions import Sequence, AsyncIterable
from dataclasses import dataclass
from datetime import datetime

from dydx.core import timestamp as ts
from trading_sdk.market.user import Funding as _Funding
from dydx_sdk.core import MarketMixin, wrap_exceptions

@dataclass(frozen=True)
class Funding(MarketMixin, _Funding):
  @wrap_exceptions
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Funding.Payment]]:
    start = start.astimezone()
    end = end.astimezone()
      
    def within(t: datetime) -> bool:
      return start <= t <= end
    
    async for batch in self.indexer.data.get_funding_payments_paged(
      self.address, subaccount=self.subaccount, ticker=self.market, start=start
    ):
      fundings = [
        Funding.Payment(amount=f['payment'], time=t)
        for f in batch
          if within(t := ts.parse(f['createdAt']))
      ]
      if fundings:
        yield fundings