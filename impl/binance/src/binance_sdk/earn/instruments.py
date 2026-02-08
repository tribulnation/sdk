from typing_extensions import Sequence, Iterable
from datetime import timedelta
from decimal import Decimal
import re

from tribulnation.sdk.core import SDK, LogicError
from tribulnation.sdk.earn.instruments import Instrument, Instruments as _Instruments
from binance.simple_earn.flexible.list import FlexibleProduct
from binance.simple_earn.fixed.list import LockedProduct, LockedProductDetail
from binance_sdk.core import SdkMixin, wrap_exceptions

def earn_url(asset: str) -> str:
  return f'https://www.binance.com/en/earn/simple-earn?asset={asset}'

tier_regex = re.compile(r'^[^-\s]+-([0-9]+(?:\.[0-9]+)?)([A-Za-z0-9]+)$')
"""Regex for parsing tier labels like '0-1BNB' -> upper bound (e.g. 1)."""

def parse_flexible_tier(label: str, asset: str) -> Decimal:
  m = tier_regex.match(label.strip())
  assert m is not None
  amount_str, symbol = m.groups()
  assert symbol == asset
  return Decimal(amount_str)

def parse_flexible(prod: FlexibleProduct) -> Iterable[Instrument]:
  if not prod['isSoldOut'] and prod['canPurchase'] and prod['status'] == 'PURCHASING':
    base_apr = prod['latestAnnualPercentageRate']
    min_qty = prod['minPurchaseAmount']
    for tier, apr in prod.get('tierAnnualPercentageRate', {}).items():
      max_qty = parse_flexible_tier(tier, prod['asset'])
      yield Instrument(
        tags=['flexible'],
        asset=prod['asset'],
        min_qty=min_qty,
        max_qty=max_qty,
        apr=base_apr + apr,
        id=prod['productId'],
      )

    yield Instrument(
      tags=['flexible'],
      asset=prod['asset'],
      apr=base_apr,
      min_qty=min_qty,
      id=prod['productId'],
    )

def parse_locked_yield_assets(detail: LockedProductDetail) -> set[str]:
  yield_assets = set[str]()
  if a := detail.get('rewardAsset'):
    yield_assets.add(a)
  if a := detail.get('boostRewardAsset'):
    yield_assets.add(a)
  if a := detail.get('extraRewardAsset'):
    yield_assets.add(a)
  return yield_assets

def parse_locked_apr(detail: LockedProductDetail) -> Decimal:
  apr = Decimal(0)
  if a := detail.get('apr'):
    apr += a
  if a := detail.get('extraRewardAPR'):
    apr += a
  if a := detail.get('boostRewardApr'):
    apr += a
  return apr

def parse_locked(prod: LockedProduct) -> Iterable[Instrument]:
  detail = prod['detail']
  if not detail['isSoldOut'] and detail['status'] == 'PURCHASING':
    asset = detail['asset']
    apr = parse_locked_apr(detail)
    yield_assets = parse_locked_yield_assets(detail)
    if len(yield_assets) > 1:
      raise LogicError(f'Multiple yield assets: {yield_assets}, instrument: {prod}')
    yield_asset = yield_assets.pop()
    yield Instrument(
      tags=['locked'],
      asset=asset,
      apr=apr,
      yield_asset=yield_asset,
      min_qty=prod['quota']['minimum'],
      max_qty=prod['quota']['totalPersonalQuota'],
      duration=timedelta(days=detail['duration']),
      id=prod['projectId'],
    )

class Instruments(SdkMixin, _Instruments):

  @SDK.method
  @wrap_exceptions
  async def _flexible_list_page(self, page: int, size: int):
    return await self.client.simple_earn.flexible.list(current=page, size=size)

  async def _flexible_list(self, size: int = 100):
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
  @wrap_exceptions
  async def _fixed_list_page(self, page: int, size: int):
    return await self.client.simple_earn.fixed.list(current=page, size=size)

  async def _fixed_list(self, size: int = 100):
    current = 1
    while True:
      r = await self._fixed_list_page(current, size)
      if not r['rows']:
        break
      yield r['rows']
      if r['total'] <= current*size:
        break
      current += 1

  @SDK.method
  async def instruments(
    self, *, tags: Sequence[Instrument.Tag] | None = None,
    assets: Sequence[str] | None = None,
  ) -> Sequence[Instrument]:

    out: list[Instrument] = []

    if tags is None or 'flexible' in tags:
      async for chunk in self._flexible_list():
        for prod in chunk:
          for inst in parse_flexible(prod):
            if assets is None or inst.asset in assets:
              out.append(inst)

    if tags is None or 'fixed' in tags:
      async for chunk in self._fixed_list():
        for prod in chunk:
          for inst in parse_locked(prod):
            if assets is None or inst.asset in assets:
              out.append(inst)
    return out
