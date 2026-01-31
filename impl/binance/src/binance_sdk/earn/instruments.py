"""
Parsing notes (proposal; confirm if you want changes):

1. **Flexible – single APR**  
   Binance returns `latestAnnualPercentageRate` and optionally `tierAnnualPercentageRate` (tiers).
   We map one product → one Flexible instrument using `latestAnnualPercentageRate` as `apr`.
   No tier splitting (unlike Bitget); we can add per-tier instruments later if needed.

2. **Flexible – max_qty**  
   API has `minPurchaseAmount` but no product-level max. We set `max_qty=None`.

3. **Fixed – optional apr**  
   `LockedProductDetail` has `apr: NotRequired[Decimal]`; sometimes only `extraRewardAPR` exists.
   We use `detail.get('apr')` when present, else `Decimal('0')`, so every row yields an instrument.

4. **Fixed – yield_asset**  
   We use `detail.get('rewardAsset') or detail['asset']` (same coin when reward asset is omitted).

5. **Fixed – min_qty / max_qty**  
   From `quota['minimum']` and `quota['totalPersonalQuota']` (personal quota as effective max).

6. **types/assets filter**  
   We fetch flexible and/or fixed only when requested by `types`. We do not pass `asset=` to
   list_paged (API takes a single asset); we fetch all pages and filter by `assets` in memory.
"""
from datetime import timedelta
from decimal import Decimal
from typing_extensions import Sequence

from sdk.core import SDK
from sdk.earn.instruments import (
  Fixed,
  Flexible,
  Instrument,
  Instruments as _Instruments,
  InstrumentType,
)
from binance_sdk.core import SdkMixin

BINANCE_EARN_URL = 'https://www.binance.com/earn'

def _to_decimal(v: Decimal | str | int) -> Decimal:
  if isinstance(v, Decimal):
    return v
  return Decimal(str(v))


def _parse_flexible_row(row: dict) -> Flexible:
  asset = row["asset"]
  apr = _to_decimal(row["latestAnnualPercentageRate"])
  min_qty = _to_decimal(row["minPurchaseAmount"])
  return Flexible(
    type="flexible",
    asset=asset,
    apr=apr,
    yield_asset=asset,
    min_qty=min_qty,
    max_qty=None,
    url=BINANCE_EARN_URL,
  )


def _parse_fixed_row(row: dict) -> Fixed:
  detail = row["detail"]
  quota = row["quota"]
  asset = detail["asset"]
  apr = detail.get("apr")
  apr_decimal = _to_decimal(apr) if apr is not None else Decimal("0")
  yield_asset = detail.get("rewardAsset") or asset
  min_qty = _to_decimal(quota["minimum"])
  max_qty = _to_decimal(quota["totalPersonalQuota"])
  duration = timedelta(days=int(detail["duration"]))
  return Fixed(
    type="fixed",
    asset=asset,
    apr=apr_decimal,
    yield_asset=yield_asset,
    min_qty=min_qty,
    max_qty=max_qty,
    url=BINANCE_EARN_URL,
    duration=duration,
  )


class Instruments(SdkMixin, _Instruments):

  @SDK.method
  async def _flexible_list_page(self, page: int, size: int):
    return await self.client.simple_earn.flexible.list(current=page, size=size)

  async def flexible_list(self, size: int = 100):
    current = 1
    while True:
      r = await self._flexible_list_page(current, size)
      if not r['rows']:
        break
      yield r['rows']
      if r['total'] <= current*size:
        break
      current += 1

  @SDK.method
  async def _fixed_list_page(self, page: int, size: int):
    return await self.client.simple_earn.fixed.list(current=page, size=size)

  async def fixed_list(self, size: int = 100):
    current = 1
    while True:
      r = await self._fixed_list_page(current, size)
      if not r['rows']:
        break
      yield r['rows']
      if r['total'] <= current*size:
        break
      current += 1

  async def instruments(
    self, *, types: Sequence[InstrumentType] | None = None,
    assets: Sequence[str] | None = None,
  ) -> Sequence[Instrument]:
    types_set = set(types) if types is not None else None
    assets_set = set(assets) if assets is not None else None
    include_flexible = types_set is None or "flexible" in types_set
    include_fixed = types_set is None or "fixed" in types_set

    out: list[Instrument] = []

    if include_flexible:
      async for chunk in self.flexible_list():
        for row in chunk:
          inst = _parse_flexible_row(row)
          if assets_set is not None and inst.asset not in assets_set:
            continue
          out.append(inst)

    if include_fixed:
      async for chunk in self.fixed_list():
        for row in chunk:
          inst = _parse_fixed_row(row)
          if assets_set is not None and inst.asset not in assets_set:
            continue
          out.append(inst)

    return out
