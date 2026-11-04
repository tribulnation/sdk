from typing_extensions import Collection, Sequence, Iterable
from datetime import timedelta
from decimal import Decimal

from tribulnation.sdk.earn.instruments import Instrument, Instruments as _Instruments
from typed_bitget.classic.earn.savings.products import SavingsProduct
from typed_bitget.uta.earn.elite.products import EliteProduct
from tribulnation.bitget.core import SdkMixin, wrap_exceptions

BITGET_SAVINGS_URL = 'https://www.bitget.com/earning/savings'


def parse_product(prod: SavingsProduct) -> Iterable[Instrument]:
  if prod['status'] != 'in_progress':
    return
  coin = prod['coin']
  period_type = prod['periodType']
  apy_list = prod['apyList']

  if period_type == 'fixed' and (period := prod.get('period')) is not None:
    duration = timedelta(days=int(period))
  else:
    duration = None

  for tier in apy_list:
    apr = Decimal(tier['currentApy']) / 100
    min_qty = Decimal(tier['minStepVal'])
    max_qty = Decimal(tier['maxStepVal'])
    yield Instrument(
      tags=[period_type],
      asset=coin,
      apr=apr,
      min_qty=min_qty,
      max_qty=max_qty,
      duration=duration,
      url=BITGET_SAVINGS_URL,
    )


def parse_elite_product(prod: EliteProduct) -> Iterable[Instrument]:
  """One instrument per subscription coin of an Elite product that is not sold out.

  `apr` is the product's minimum APR (the venue quotes a range, in percent).
  """
  if prod['sellOut'] == 'YES':
    return
  for item in prod['subscriptionCoinList']:
    asset = item['subscriptionCoin']
    yield Instrument(
      tags=['staking'],
      asset=asset,
      yield_asset=prod['coin'] if prod['coin'] != asset else None,
      apr=Decimal(prod['minApr']) / 100,
      min_qty=Decimal(min_amount) if (min_amount := item.get('minAmount')) else None,
      max_qty=Decimal(quota) if (quota := item.get('remainQuota')) else None,
      id=prod['productId'],
    )


def selected(
  inst: Instrument,
  *,
  tags: Collection[Instrument.Tag] | None,
  assets: Collection[str] | None,
) -> bool:
  """Whether an instrument passes the asset and tag filters."""
  return (assets is None or inst.asset in assets) and (
    tags is None or set(inst.tags).issubset(tags)
  )


class Instruments(SdkMixin, _Instruments):
  @wrap_exceptions
  async def instruments(
    self,
    *,
    tags: Collection[Instrument.Tag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    """Savings products on a Classic account; on-chain Elite products on a UTA account.

    The Classic savings API refuses UTA accounts, whose earn API lists only Elite products.
    """
    if await self.is_uta():
      products = await self.client.uta.earn.elite.products()
      parsed = [inst for prod in products for inst in parse_elite_product(prod)]
    else:
      savings = await self.client.classic.earn.savings.products()
      parsed = [inst for prod in savings for inst in parse_product(prod)]
    return [inst for inst in parsed if selected(inst, tags=tags, assets=assets)]
