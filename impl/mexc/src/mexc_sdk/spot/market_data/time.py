from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.market.market_data.time import Time as _Time 

from mexc.core import timestamp as ts
from mexc_sdk.core import SdkMixin, wrap_exceptions

@dataclass
class Time(_Time, SdkMixin):
  @wrap_exceptions
  async def time(self) -> datetime:
    r = await self.client.spot.time()
    return ts.parse(r['serverTime'])
