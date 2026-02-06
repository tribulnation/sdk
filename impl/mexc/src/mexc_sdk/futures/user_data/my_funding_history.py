from datetime import datetime
from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market.user_data.my_funding_history import MyFundingHistory as _MyFundingHistory, Funding

from mexc.core import timestamp as ts
from mexc_sdk.core import MarketMixin, wrap_exceptions
from mexc.futures.user_data.my_funding_history import PositionType

@dataclass
class MyFundingHistory(_MyFundingHistory, MarketMixin):
  @wrap_exceptions
  async def my_funding_history(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Funding]]:
    page_num = 1
    num_pages = None
    while num_pages is None or page_num <= num_pages:
      r = await self.client.futures.my_funding_history(self.instrument)
      if not 'data' in r:
        raise ApiError(r)
      else:
        yield [
          Funding(
            rate=Decimal(f['rate']),
            funding=Decimal(f['funding']),
            time=t,
            side='LONG' if f['positionType'] == PositionType.long else 'SHORT',
          )
          for f in r['data']['resultList']
            if start <= (t := ts.parse(f['settleTime'])) <= end
        ]
        num_pages = r['data']['totalPage']
        page_num += 1
