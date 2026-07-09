from typing_extensions import AsyncIterable, Sequence
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.market import Trade

from mexc.core import timestamp as ts
from mexc.spot.account.trades import AccountTrade
from mexc.spot.streams.core.proto import PrivateDealsV3Api

from tribulnation.mexc.core.exc import wrap_exceptions
from .mixin import MarketMixin

def _parse_trade(t: AccountTrade) -> Trade:
  sign = 1 if t.get('isBuyer') else -1
  fee = None
  if (a := t.get('commissionAsset')) and (c := t.get('commission')):
    fee = Trade.Fee(asset=a, amount=Decimal(c))
  time = t.get('time')
  if time is None:
    raise ValueError('Missing trade time')
  return Trade(
    id=str(t.get('id')),
    price=Decimal(t.get('price') or '0'),
    qty=Decimal(t.get('qty') or '0') * sign,
    time=time.astimezone() if isinstance(time, datetime) else ts.parse(time).astimezone(),
    maker=bool(t.get('isMaker')),
    fee=fee,
    details=t,
  )


@wrap_exceptions
async def trades_stream(self: MarketMixin) -> AsyncIterable[Trade]:
  async with self.subscribe_my_trades() as s:
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


@wrap_exceptions
async def trades_history(self: MarketMixin, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
  trades = await self.client.spot.account.trades(
    symbol=self.instrument,
    start_time=start,
    end_time=end,
    recv_window=self.shared.recv_window,
    validate=self.shared.validate,
  )
  yield [_parse_trade(t) for t in trades]
