from typing_extensions import AsyncIterable, Sequence
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta

from trading_sdk.market.data import Funding as _Funding
from dydx.core import timestamp as ts
from dydx_sdk.core import MarketMixin, IndexerDataMixin, wrap_exceptions

@dataclass
class Funding(MarketMixin, IndexerDataMixin, _Funding):
  @wrap_exceptions
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Funding.Funding]]:
    start = start.astimezone()
    end = end.astimezone()
    async for page in self.indexer_data.get_historical_funding_paged(self.market, end=end):
      fundings = [
        _Funding.Funding(rate=Decimal(f['rate']), time=time)
        for f in page
          if (time := ts.parse(f['effectiveAt'])) >= start
      ]
      if fundings:
        yield fundings
      else:
        break

  @wrap_exceptions
  async def next(self) -> _Funding.Funding:
    market = await self.indexer_data.get_market(self.market)
    now = datetime.now().astimezone()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return _Funding.Funding(
      rate=Decimal(market['nextFundingRate']),
      time=next_hour
    )