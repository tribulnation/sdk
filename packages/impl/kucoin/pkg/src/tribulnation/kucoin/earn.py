"""Kucoin simple savings and staking; structured dual investments are excluded."""

from datetime import timedelta
from decimal import Decimal
from typing_extensions import Collection, Sequence
from tribulnation.sdk.earn import Earn as BaseEarn
from tribulnation.sdk.earn.instruments import Instrument
from typed_kucoin.earn.savings_products import SavingsProduct
from typed_kucoin.earn.staking_products import StakingProductItem
from typed_kucoin.earn.kcs_staking_products import KcsStakingProductItem
from typed_kucoin.earn.eth_staking_products import EthStakingProductItem
from typed_kucoin.earn.promotion_products import PromotionProductItem
from .core import Mixin

Product = (
  SavingsProduct
  | StakingProductItem
  | KcsStakingProductItem
  | EthStakingProductItem
  | PromotionProductItem
)


def parse_product(row: Product, *, staking: bool) -> Instrument:
  """Preserve rate units and distinguish a fixed duration from flexible access."""
  tags: list[Instrument.Tag] = ['flexible' if row['type'] == 'DEMAND' else 'fixed']
  if staking:
    tags.append('staking')
  if row.get('newUserOnly'):
    tags.append('new-users')
  return Instrument(
    id=row['id'],
    asset=row['currency'],
    tags=tags,
    apr=Decimal(row['returnRate']),
    yield_asset=row['incomeCurrency']
    if row['incomeCurrency'] != row['currency']
    else None,
    min_qty=Decimal(row['userLowerLimit']),
    max_qty=Decimal(row['userUpperLimit']),
    duration=timedelta(days=row['duration']) if row['type'] == 'TIME' else None,
  )


class Earn(Mixin, BaseEarn):
  """List the five simple product families supported by the APR contract."""

  async def instruments(
    self,
    *,
    tags: Collection[Instrument.Tag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    """Exclude dual investments whose contingent principal conversion is not modelled."""
    rows: list[tuple[Product, bool]] = []
    rows.extend(
      (row, False) for row in await self.call(self.client.earn.savings_products)
    )
    rows.extend(
      (row, False) for row in await self.call(self.client.earn.promotion_products)
    )
    rows.extend(
      (row, True) for row in await self.call(self.client.earn.staking_products)
    )
    rows.extend(
      (row, True) for row in await self.call(self.client.earn.kcs_staking_products)
    )
    rows.extend(
      (row, True) for row in await self.call(self.client.earn.eth_staking_products)
    )
    instruments = [parse_product(row, staking=staking) for row, staking in rows]
    return [
      item
      for item in instruments
      if (assets is None or item.asset in assets)
      and (tags is None or set(tags).intersection(item.tags))
    ]
