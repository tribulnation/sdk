"""Bybit's yield-bearing product catalogues, mapped onto SDK `Instrument`s.

Three public catalogues back this surface: `finance.fixed_saving` for fixed-term
savings, and `finance.easy_onchain` for open-ended savings and liquid staking, the
latter two discriminated by `category` off one endpoint. All three carry APR,
min/max stake and a product id, which is what `Instrument` needs.
"""

from typing_extensions import Collection, Literal, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from tribulnation.sdk.core import SDK
from tribulnation.sdk.earn import Instruments as _Instruments
from tribulnation.sdk.earn.instruments import Instrument
from typed_bybit.finance.easy_onchain.product_info import EarnProduct
from typed_bybit.finance.fixed_saving.product import FixedSavingProduct

from tribulnation.bybit.core import Mixin

EasyOnchainCategory = Literal['FlexibleSaving', 'OnChain']
"""The two catalogues `finance.easy_onchain.product_info` serves."""

EASY_ONCHAIN_TAGS: dict[EasyOnchainCategory, Instrument.Tag] = {
  'FlexibleSaving': 'flexible',
  'OnChain': 'staking',
}
"""Which SDK tag each Easy & On-Chain Earn catalogue maps onto."""

NO_CAP = Decimal(-1)
"""Bybit's "no upper limit" sentinel for a maximum stake amount."""


def parse_percent(value: str) -> Decimal:
  """Read one of Bybit's percent-formatted rates, e.g. `"2.12%"`, as a fraction of 1."""
  return Decimal(value.rstrip('%')) / 100


def parse_duration(raw: str) -> timedelta | None:
  """Parse a fixed-saving term, e.g. `"7d"` or `"8h"`.

  Bybit also documents a `"2m"` form, left unparsed here: `m` is ambiguous between
  months and minutes, and no product in the live catalogue uses it.
  """
  unit, value = raw[-1], raw[:-1]
  if unit == 'd':
    return timedelta(days=int(value))
  if unit == 'h':
    return timedelta(hours=int(value))
  return None


def parse_fixed_saving(product: FixedSavingProduct) -> Instrument:
  """Map one fixed-term saving product onto an `Instrument`.

  A product's APR lives in one of two lists. `tieredApyList` keys it by staked
  amount; `interestCoinApyList` keys it by reward coin, which may differ from the
  staked coin -- that difference is exactly `Instrument.yield_asset`.
  """
  tiers = product.get('tieredApyList')
  interest_coins = product.get('interestCoinApyList')
  yield_asset = None
  if tiers:
    apr = parse_percent(tiers[0]['apy'])
  elif interest_coins:
    best = interest_coins[0]
    apr = parse_percent(best['apy'])
    yield_asset = best['coin'] if best['coin'] != product['coin'] else None
  else:
    apr = Decimal(0)
  max_qty = product['maxStakeAmount']
  return Instrument(
    # A `specialUserGroupRequired` product is a restricted promotional one, which is
    # exactly what the SDK's 'new-users' tag means.
    tags=['new-users'] if product.get('specialUserGroupRequired') else ['fixed'],
    asset=product['coin'],
    apr=apr,
    yield_asset=yield_asset,
    min_qty=product['minStakeAmount'],
    max_qty=max_qty if max_qty != NO_CAP else None,
    duration=parse_duration(product['duration']),
    id=product['productId'],
  )


def parse_easy_onchain(
  category: EasyOnchainCategory, product: EarnProduct
) -> Instrument:
  """Map one Easy or On-Chain Earn product onto an `Instrument`.

  `term` is the term length in days, and `0` or absent on an open-ended product --
  which most of both catalogues is, but not all: the On-Chain BTC product runs a
  45-day fixed term, so it carries `'fixed'` on top of its category's own tag.
  """
  term = product.get('term') or 0
  tags: list[Instrument.Tag] = [EASY_ONCHAIN_TAGS[category]]
  if term:
    tags.append('fixed')
  return Instrument(
    tags=tags,
    asset=product['coin'],
    apr=parse_percent(product['estimateApr']),
    min_qty=product['minStakeAmount'],
    max_qty=product['maxStakeAmount'],
    duration=timedelta(days=term) if term else None,
    id=product['productId'],
  )


@dataclass(kw_only=True, frozen=True)
class Instruments(Mixin, _Instruments):
  """Bybit's Earn catalogues."""

  @SDK.method
  async def fixed_saving_instruments(self) -> Sequence[Instrument]:
    """Fetch the fixed-term saving catalogue."""
    products = await self.call_bybit(
      lambda: self.client.finance.fixed_saving.product(validate=self.validate)
    )
    return [parse_fixed_saving(p) for p in products['list']]

  @SDK.method
  async def easy_onchain_instruments(
    self, category: EasyOnchainCategory
  ) -> Sequence[Instrument]:
    """Fetch one Easy & On-Chain Earn catalogue.

    Args:
      category: `'FlexibleSaving'` for open-ended savings, `'OnChain'` for staking.
    """
    products = await self.call_bybit(
      lambda: self.client.finance.easy_onchain.product_info(
        category, validate=self.validate
      )
    )
    return [
      parse_easy_onchain(category, p)
      for p in products['list']
      if p['status'] == 'Available'
    ]

  async def instruments(
    self,
    *,
    tags: Collection[Instrument.Tag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    """Fetch Bybit's yield-bearing instruments.

    Covers fixed-term savings, open-ended savings and liquid staking. Two of Bybit's
    other Earn lines are deliberately left out: Hold-to-Earn has no subscription
    step, no min/max stake and no id to act against, and Dual Asset -- the venue's
    `'one-time'` analogue -- carries no yield in its catalogue at all, only in a
    per-product quote call, so a listing would have to fetch one request per product
    to report an APR.

    Args:
      tags: Keep instruments carrying at least one of these tags.
      assets: Keep instruments subscribed with one of these assets.
    """
    out = list(await self.fixed_saving_instruments())
    out += await self.easy_onchain_instruments('FlexibleSaving')
    out += await self.easy_onchain_instruments('OnChain')
    if assets is not None:
      out = [i for i in out if i.asset in assets]
    if tags is not None:
      out = [i for i in out if any(t in tags for t in i.tags)]
    return out
