from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_sdk.market.user import Trades as _Trades
from hyperliquid.core import timestamp as ts
from hyperliquid.info.methods.user_fills_by_time import UserFill
from hyperliquid.streams.user_fills import WsFill
from hyperliquid_sdk.perps.core import PerpMixin

def parse_fill(f: UserFill | WsFill) -> _Trades.Trade:
  sign = 1 if f['side'] == 'B' else -1
  return _Trades.Trade(
    id=str(f['tid']),
    price=Decimal(f['px']),
    qty=Decimal(f['sz']) * sign,
    time=ts.parse(f['time']).astimezone(),
    maker=not f['crossed'],
    fee=_Trades.Trade.Fee(
      amount=Decimal(f['fee']),
      asset=f['feeToken'],
    ),
    details=f
  )

@dataclass(frozen=True)
class Trades(PerpMixin, _Trades):
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[_Trades.Trade]]:
    start_ts, end_ts = ts.dump(start), ts.dump(end)
    async for chunk in self.client.info.user_fills_by_time_paged(self.address, start_ts, end_time=end_ts):
      yield [parse_fill(f) for f in chunk if f['coin'] == self.asset_name]

  async def stream(self) -> AsyncIterable[_Trades.Trade]:
    async for chunk in self.subscribe_user_fills():
      for f in chunk:
        if f['coin'] == self.asset_name:
          yield parse_fill(f)
