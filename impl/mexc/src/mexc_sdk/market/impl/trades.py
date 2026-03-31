from typing_extensions import AsyncIterable, Sequence
from datetime import datetime
from decimal import Decimal

from trading_sdk.core import Stream
from trading_sdk.market import Trade

from mexc.core import timestamp as ts
from mexc.spot.user_data.my_trades import Trade as MexcTrade
from mexc.spot.streams.core.proto import PrivateDealsV3Api

from mexc_sdk.core.exc import wrap_exceptions
from .mixin import MarketMixin


def _parse_trade(t: MexcTrade) -> Trade:
  sign = 1 if t["isBuyer"] else -1
  fee = None
  if (a := t.get("commissionAsset")) and (c := t.get("commission")):
    fee = Trade.Fee(asset=a, amount=Decimal(c))
  return Trade(
    id=t["id"],
    price=Decimal(t["price"]),
    qty=Decimal(t["qty"]) * sign,
    time=ts.parse(t["time"]).astimezone(),
    maker=t["isMaker"],
    fee=fee,
    details=t,
  )


@wrap_exceptions
async def trades_stream(self: MarketMixin) -> Stream[Trade]:
  s = await self.subscribe_my_trades()

  async def gen():
    async for msg in s:
      # PrivateDealsV3Api corresponds to a single fill.
      if not isinstance(msg, PrivateDealsV3Api):
        continue
      # No symbol field in the proto; it is carried by wrapper in some streams, but not here.
      # So we yield as-is and rely on upstream filtering by subscription (user stream is account-wide).
      side = "BUY" if msg.trade_type == 1 else "SELL"
      sign = 1 if side == "BUY" else -1
      yield Trade(
        id=msg.trade_id,
        price=Decimal(msg.price),
        qty=Decimal(msg.quantity) * sign,
        time=ts.parse(msg.time).astimezone(),
        maker=bool(msg.is_maker),
        fee=Trade.Fee(asset=msg.fee_currency, amount=Decimal(msg.fee_amount)),
        details=msg,
      )

  return Stream(gen(), s.unsubscribe)


@wrap_exceptions
async def trades_history(self: MarketMixin, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
  async for chunk in self.client.spot.my_trades_paged(
    self.instrument,
    start=start,
    end=end,
    recvWindow=self.shared.recvWindow,
    validate=self.shared.validate,
  ):
    yield [_parse_trade(t) for t in chunk]

