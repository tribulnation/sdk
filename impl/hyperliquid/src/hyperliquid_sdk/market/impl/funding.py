from typing_extensions import AsyncIterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from trading_sdk.market import FundingRate, FundingPayment

from hyperliquid.core import timestamp as ts
from hyperliquid_sdk.core import wrap_exceptions
from .mixin import PerpMarketMixin


@wrap_exceptions
async def next_funding(self: PerpMarketMixin) -> FundingRate:
  perp_meta, asset_ctxs = await self.shared.load_perp_meta()
  if perp_meta["universe"][self.asset_idx]["name"] != self.asset_name:
    raise ValueError(
      f"Expected asset {self.asset_name} at index {self.asset_idx}, got {perp_meta['universe'][self.asset_idx]['name']}"
    )

  funding = Decimal(asset_ctxs[self.asset_idx]["funding"])
  now = datetime.now().astimezone()
  next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
  return FundingRate(rate=funding, time=next_time)


@wrap_exceptions
async def funding_history(self: PerpMarketMixin, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingRate]]:
  start_ts, end_ts = ts.dump(start), ts.dump(end)
  async for chunk in self.client.info.funding_history_paged(self.asset_name, start_ts, end_time=end_ts):
    yield [
      FundingRate(rate=Decimal(entry["fundingRate"]), time=ts.parse(entry["time"]).astimezone())
      for entry in chunk
    ]


@wrap_exceptions
async def funding_payments(self: PerpMarketMixin, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingPayment]]:
  start_ts, end_ts = ts.dump(start), ts.dump(end)
  async for chunk in self.client.info.user_funding_paged(self.address, start_ts, end_time=end_ts):
    payments: list[FundingPayment] = []
    for p in chunk:
      if p["delta"]["coin"] != self.asset_name:
        continue
      t = ts.parse(p["time"]).astimezone()
      if t < start or t > end:
        continue
      payments.append(FundingPayment(amount=Decimal(p["delta"]["usdc"]), time=t))
    if payments:
      yield payments

