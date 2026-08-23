from typing_extensions import AsyncIterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.market import FundingRate, NextFunding, FundingPayment

from typed_hyperliquid.core import timestamp_millis as ts
from tribulnation.hyperliquid.core import wrap_exceptions
from .mixin import PerpMarketMixin


@wrap_exceptions
async def next_funding(self: PerpMarketMixin) -> NextFunding:
  _, perp_meta, asset_ctxs = await self.shared.load_perp_meta_for_dex(self.dex_name, refetch=True)
  if perp_meta["universe"][self.asset_idx]["name"] != self.asset_name:
    raise ValueError(
      f"Expected asset {self.asset_name} at index {self.asset_idx}, got {perp_meta['universe'][self.asset_idx]['name']}"
    )

  funding = Decimal(asset_ctxs[self.asset_idx]["funding"])
  now = datetime.now().astimezone()
  next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
  return NextFunding(rate=funding, time=next_time, interval=timedelta(hours=1))


@wrap_exceptions
async def funding_rates(self: PerpMarketMixin, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Sequence[FundingRate]]:
  start_time = start if start is not None else ts.parse(0)
  async for chunk in self.client.info.funding_history_paged(
    coin=self.asset_name, start_time=start_time, end_time=end,
  ):
    yield [
      FundingRate(
        rate=Decimal(entry["fundingRate"]),
        time=entry['time'].astimezone(),
        premium=Decimal(premium) if (premium := entry.get("premium")) is not None else None,
      )
      for entry in chunk
    ]


@wrap_exceptions
async def funding_payments(self: PerpMarketMixin, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingPayment]]:
  async for chunk in self.client.info.user_funding_paged(
    user=self.address, start_time=start, end_time=end,
  ):
    payments: list[FundingPayment] = []
    for p in chunk:
      if p["delta"]["coin"] != self.asset_name:
        continue
      t = p['time'].astimezone()
      if t < start or t > end:
        continue
      payments.append(FundingPayment(amount=Decimal(p["delta"]["usdc"]), time=t))
    if payments:
      yield payments
