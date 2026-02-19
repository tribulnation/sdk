from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta

from trading_sdk import LogicError
from trading_sdk.market.data import Funding as _Funding
from hyperliquid.core import timestamp as ts
from hyperliquid_sdk.perps.core import PerpMixin

@dataclass(frozen=True)
class Funding(PerpMixin, _Funding):
  async def next(self) -> _Funding.Funding:
    perp_meta, asset_ctxs = await self.client.info.perp_meta_and_asset_ctxs(self.dex)
    if perp_meta['universe'][self.asset_idx]['name'] != self.asset_name:
      raise LogicError(f'Expected asset {self.asset_name} at index {self.asset_idx}, got {perp_meta["universe"][self.asset_idx]["name"]}')
    
    funding = Decimal(asset_ctxs[self.asset_idx]['funding'])
    next_time = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1) # next hour
    return _Funding.Funding(rate=funding, time=next_time)

  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Funding.Funding]]:
    start_ts, end_ts = ts.dump(start), ts.dump(end)
    async for chunk in self.client.info.funding_history_paged(self.asset_name, start_ts, end_time=end_ts):
      yield [
        _Funding.Funding(
          rate=Decimal(entry['fundingRate']),
          time=ts.parse(entry['time'])
        )
        for entry in chunk
      ]
