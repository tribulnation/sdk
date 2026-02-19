from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_sdk.market.user import Funding as _Funding
from hyperliquid.core import timestamp as ts
from hyperliquid_sdk.perps.core import PerpMixin

@dataclass(frozen=True)
class Funding(PerpMixin, _Funding):
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Funding.Payment]]:
    start_ts, end_ts = ts.dump(start), ts.dump(end)
    async for chunk in self.client.info.user_funding_paged(self.address, start_ts, end_time=end_ts):
      yield [
        _Funding.Payment(
          amount=Decimal(p['delta']['usdc']),
          time=ts.parse(p['time']),
        )
        for p in chunk
          if p['delta']['coin'] == self.asset_name
      ]
