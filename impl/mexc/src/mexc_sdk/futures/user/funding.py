from datetime import datetime
from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.user import Funding as _Funding

from mexc.core import timestamp as ts
from mexc_sdk.core import PerpMixin, wrap_exceptions

@dataclass(frozen=True)
class Funding(PerpMixin, _Funding):
  @wrap_exceptions
  def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Funding.Payment]]:
    async def iterator():
      page_num = 1
      num_pages = None
      while num_pages is None or page_num <= num_pages:
        r = await self.client.futures.my_funding_history(self.instrument)
        payments: list[_Funding.Payment] = []
        for f in r['resultList']:
          t = ts.parse(f['settleTime']).astimezone()
          if start <= t <= end:
            payments.append(_Funding.Payment(
              amount=Decimal(f['funding']),
              time=t,
            ))
        yield payments
        num_pages = r.get('totalPage')
        page_num += 1
    return iterator()
