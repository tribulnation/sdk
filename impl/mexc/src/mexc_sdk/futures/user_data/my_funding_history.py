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
class MyFundingHistory(MarketMixin, _MyFundingHistory):
  @wrap_exceptions
  async def _my_funding_history_impl(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Funding]]:
    page_num = 1
    num_pages = None
    info  = await self.client.futures.contract_info(self.instrument)
    while num_pages is None or page_num <= num_pages:
      r = await self.client.futures.my_funding_history(self.instrument)
      yield [
        Funding(
          rate=Decimal(f['rate']),
          funding=Decimal(f['funding']),
          time=t,
          currency=info['settleCoin'],
          side='LONG' if f['positionType'] == PositionType.long else 'SHORT',
        )
        for f in r['resultList']
          if start <= (t := ts.parse(f['settleTime'])) <= end
      ]
      num_pages = r['totalPage']
      page_num += 1
