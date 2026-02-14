from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.market.market_data.funding_rate_history import (
  FundingRateHistory as _FundingRateHistory, Funding
)

from dydx.core import timestamp as ts
from dydx_sdk.core import MarketMixin, IndexerDataMixin, wrap_exceptions, perp_name

@dataclass
class FundingRateHistory(IndexerDataMixin, MarketMixin, _FundingRateHistory):
  @wrap_exceptions
  async def _funding_rate_history_impl(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[Funding]]:
    start = start.astimezone()
    end = end.astimezone()
    async for page in self.indexer_data.get_historical_funding_paged(self.market, end=end):
      fundings = [
        Funding(rate=Decimal(f['rate']), time=time)
        for f in page
          if (time := ts.parse(f['effectiveAt'])) >= start
      ]
      if fundings:
        yield fundings
      else:
        break
    