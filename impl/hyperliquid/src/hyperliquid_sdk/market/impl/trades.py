from typing_extensions import AsyncIterable, Sequence, Any
from datetime import datetime
from decimal import Decimal

from trading_sdk.core import Stream
from trading_sdk.market import Trade

from hyperliquid_sdk.core import wrap_exceptions
from .mixin import SpotMarketMixin, PerpMarketMixin


def _parse_time(value: Any) -> datetime:
  from hyperliquid.core import timestamp as ts
  return ts.parse(value).astimezone()


@wrap_exceptions
async def trades_stream(self: SpotMarketMixin | PerpMarketMixin) -> Stream[Trade]:
  fills = await self.subscribe_user_fills()

  async def stream():
    async for chunk in fills:
      # Both spot and perps subscriptions aggregate by time.
      if not chunk.get("isSnapshot"):
        for f in (chunk.get("fills") or []):
          if f.get("coin") != self.asset_name:
            continue
          sign = 1 if f["side"] == "B" else -1
          yield Trade(
            id=str(f.get("tid")),
            price=Decimal(f["px"]),
            qty=Decimal(f["sz"]) * sign,
            time=_parse_time(f["time"]),
            maker=not f.get("crossed", False),
            fee=Trade.Fee(amount=Decimal(f["fee"]), asset=f["feeToken"]) if f.get("fee") is not None else None,
            details=f,
          )

  return Stream(stream(), fills.unsubscribe)


def trades_history(self: SpotMarketMixin | PerpMarketMixin, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
  async def gen():
    from hyperliquid.core import timestamp as ts

    start_ts, end_ts = ts.dump(start), ts.dump(end)
    async for chunk in self.client.info.user_fills_by_time_paged(self.address, start_ts, end_time=end_ts):
      trades: list[Trade] = []
      for f in chunk:
        if f.get("coin") != self.asset_name:
          continue
        sign = 1 if f["side"] == "B" else -1
        trades.append(
          Trade(
            id=str(f.get("tid")),
            price=Decimal(f["px"]),
            qty=Decimal(f["sz"]) * sign,
            time=ts.parse(f["time"]).astimezone(),
            maker=not f.get("crossed", False),
            fee=Trade.Fee(amount=Decimal(f["fee"]), asset=f["feeToken"]),
            details=f,
          )
        )
      if trades:
        yield trades

  return gen()

