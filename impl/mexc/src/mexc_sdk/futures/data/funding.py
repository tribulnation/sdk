from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing_extensions import AsyncIterable, Sequence

from trading_sdk.market.data import Funding as _Funding

from mexc.core import timestamp as ts
from mexc_sdk.core import PerpMixin, wrap_exceptions

@dataclass(frozen=True)
class Funding(PerpMixin, _Funding):
  @wrap_exceptions
  def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Funding.Funding]]:
    async def iterator():
      async for chunk in self.client.futures.funding_rate_history_paged(self.instrument):
        out: list[_Funding.Funding] = []
        for f in chunk:
          t = ts.parse(f['settleTime'])
          if start <= t <= end:
            out.append(_Funding.Funding(
              rate=Decimal(f['fundingRate']),
              time=t,
            ))
        yield out
    return iterator()

  @wrap_exceptions
  async def next(self) -> _Funding.Funding:
    r = await self.client.futures.funding_rate(self.instrument)
    return _Funding.Funding(
      rate=Decimal(r['fundingRate']),
      time=ts.parse(r['nextSettleTime']),
    )
