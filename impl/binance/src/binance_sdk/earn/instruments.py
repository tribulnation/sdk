"""
Parsing notes:

1. **Flexible – APR and tiers**
   - Binance returns `latestAnnualPercentageRate` plus optional `tierAnnualPercentageRate` and
     `airDropPercentageRate`.
   - We map one product → one `Flexible` instrument.
   - For APR we take:
       - the maximum APR among `latestAnnualPercentageRate` and all values in
         `tierAnnualPercentageRate` (when present), and
       - we then add `airDropPercentageRate` (if present), treating it as extra yield in the same
         reward asset.
   - We still do not split products by tier; that could be added later if we want per‑tier rows.

2. **Flexible – max_qty**
   - API has `minPurchaseAmount` but no product-level max. We set `max_qty=None`.

3. **Fixed – APR and extra / boost rewards**
   - `LockedProductDetail` has `apr`, `extraRewardAPR` and `boostRewardApr`, each with a
     corresponding `*Asset` field.
   - We compute a single APR in the chosen `yield_asset` by summing:
       - `apr` (when present),
       - `extraRewardAPR` when `extraRewardAsset == yield_asset`, and
       - `boostRewardApr` when `boostRewardAsset == yield_asset`.
   - When `boostRewardAsset` is present and **different** from `rewardAsset` / `yield_asset`, we
     ignore the boost APR because our schema cannot represent multi‑asset rewards; see the inline
     comment in `_parse_fixed_row`.

4. **Fixed – yield_asset**
   - We use `detail.get('rewardAsset') or detail['asset']` (same coin when reward asset is omitted).

5. **Fixed – min_qty / max_qty**
   - From `quota['minimum']` and `quota['totalPersonalQuota']` (personal quota as effective max).

6. **types/assets filter**
   - We fetch flexible and/or fixed only when requested by `types`. We do not pass `asset=` to
     `list_paged` (API takes a single asset); we fetch all pages and filter by `assets` in memory.
"""
from datetime import timedelta
from decimal import Decimal
import re
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

BINANCE_EARN_URL_TMPL = 'https://www.binance.com/en/earn/simple-earn?asset={asset}'


def _earn_url(asset: str) -> str:
  return BINANCE_EARN_URL_TMPL.format(asset=asset)


def _to_decimal(v: Decimal | str | int) -> Decimal:
  if isinstance(v, Decimal):
    return v
  return Decimal(str(v))


def _parse_flexible_row(row: dict) -> Flexible:
  asset = row["asset"]
  # Base APR from latestAnnualPercentageRate
  apr = _to_decimal(row["latestAnnualPercentageRate"])

  # Incorporate tierAnnualPercentageRate if present by taking the maximum tier APR.
  tiers = row.get("tierAnnualPercentageRate") or {}
  if isinstance(tiers, dict) and tiers:
    try:
      tier_aprs = [_to_decimal(v) for v in tiers.values()]
    except Exception:
      tier_aprs = []
    if tier_aprs:
      max_tier_apr = max(tier_aprs)
      if max_tier_apr > apr:
        apr = max_tier_apr

  # Add any airDropPercentageRate on top of the base APR – Binance expresses this as an additional
  # percentage rate, and the public API does not expose a separate reward asset for it here. We
  # treat it as extra yield in the same asset.
  air_drop = row.get("airDropPercentageRate")
  if air_drop is not None:
    apr += _to_decimal(air_drop)

  min_qty = _to_decimal(row["minPurchaseAmount"])
  return Flexible(
    type="flexible",
    asset=asset,
    apr=apr,
    yield_asset=asset,
    min_qty=min_qty,
    max_qty=None,
    url=_earn_url(asset),
  )


_TIER_LABEL_RE = re.compile(r"^[^-\s]+-([0-9]+(?:\.[0-9]+)?)([A-Za-z0-9]+)$")


def _parse_tier_max_qty(label: str, asset: str) -> Decimal | None:
  """Best-effort parse of tier label like '0-1BNB' -> upper bound (e.g. 1).

  If the label format is unexpected or the unit does not match the asset symbol,
  we return None and leave max_qty unset for that tier.
  """
  m = _TIER_LABEL_RE.match(label.strip())
  if not m:
    return None
  amount_str, symbol = m.groups()
  if symbol.upper() != asset.upper():
    return None
  try:
    return _to_decimal(amount_str)
  except Exception:
    return None


def _parse_flexible_rows(row: dict) -> list[Flexible]:
  """Return one Flexible instrument per tier **plus** a base instrument.

  - Base instrument: APR = latestAnnualPercentageRate (+ airDropPercentageRate if present),
    with no upper limit (`max_qty=None`).
  - For each tier:
      APR = base_APR + tierAnnualPercentageRate[tier_label]
      (and we again include airDropPercentageRate if present),
      and we attempt to set `max_qty` from the tier label when possible.
  """
  asset = row["asset"]
  base_apr = _to_decimal(row["latestAnnualPercentageRate"])
  air_drop = row.get("airDropPercentageRate")
  tiers = row.get("tierAnnualPercentageRate") or {}
  min_qty = _to_decimal(row["minPurchaseAmount"])

  # Base APR (used for the unlimited instrument and as the base for tiers)
  base_apr_effective = base_apr
  if air_drop is not None:
    base_apr_effective += _to_decimal(air_drop)

  instruments: list[Flexible] = []

  # Base instrument with no upper limit
  instruments.append(
    Flexible(
      type="flexible",
      asset=asset,
      apr=base_apr_effective,
      yield_asset=asset,
      min_qty=min_qty,
      max_qty=None,
      url=_earn_url(asset),
    )
  )

  # Tier instruments with per-tier caps where we can infer them
  if isinstance(tiers, dict) and tiers:
    for tier_label, tier_value in tiers.items():
      tier_apr = _to_decimal(tier_value)
      apr = base_apr_effective + tier_apr
      max_qty = _parse_tier_max_qty(tier_label, asset)
      instruments.append(
        Flexible(
          type="flexible",
          asset=asset,
          apr=apr,
          yield_asset=asset,
          min_qty=min_qty,
          max_qty=max_qty,
          url=_earn_url(asset),
        )
      )

  return instruments


def _parse_fixed_row(row: dict) -> Fixed:
  detail = row["detail"]
  quota = row["quota"]
  asset = detail["asset"]
  yield_asset = detail.get("rewardAsset") or asset

  # Build a single APR for the chosen yield_asset by combining:
  # - base APR (`apr`),
  # - extraRewardAPR when extraRewardAsset == yield_asset,
  # - boostRewardApr when boostRewardAsset == yield_asset.
  # If boostRewardAsset is present but different from yield_asset we ignore it (see comment below).
  total_apr = Decimal("0")

  base_apr = detail.get("apr")
  if base_apr is not None:
    total_apr += _to_decimal(base_apr)

  extra_apr = detail.get("extraRewardAPR")
  extra_asset = detail.get("extraRewardAsset")
  if extra_apr is not None and (extra_asset is None or extra_asset == yield_asset):
    total_apr += _to_decimal(extra_apr)

  boost_apr = detail.get("boostRewardApr")
  boost_asset = detail.get("boostRewardAsset")
  if boost_apr is not None:
    if boost_asset is None or boost_asset == yield_asset:
      total_apr += _to_decimal(boost_apr)
    else:
      # NOTE:
      # Binance can pay boost rewards in a different asset than the main rewardAsset. Our current
      # Earn schema only supports a single `yield_asset` per instrument, so we cannot faithfully
      # represent a multi‑asset reward stream. In that case we intentionally *ignore* the boost
      # APR instead of trying to coerce it into the main yield asset.
      pass

  min_qty = _to_decimal(quota["minimum"])
  max_qty = _to_decimal(quota["totalPersonalQuota"])
  duration = timedelta(days=int(detail["duration"]))
  return Fixed(
    type="fixed",
    asset=asset,
    apr=total_apr,
    yield_asset=yield_asset,
    min_qty=min_qty,
    max_qty=max_qty,
    url=_earn_url(asset),
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
          for inst in _parse_flexible_rows(row):
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
