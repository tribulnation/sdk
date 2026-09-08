"""Binance Earn instruments, merged from every rate-bearing product family."""

from typing_extensions import Any, Collection, Coroutine, Sequence
from dataclasses import dataclass
from datetime import timedelta
import asyncio

from tribulnation.sdk.core import SDK
from tribulnation.sdk.earn.instruments import (
  Instrument,
  InstrumentTag,
  Instruments as _Instruments,
)
from typed_binance.spot.http.simple_earn.flexible.list import FlexibleProduct
from typed_binance.spot.http.simple_earn.locked.list import LockedProduct
from typed_binance.spot.http.staking.on_chain_yields.locked.list import (
  OnChainYieldsLockedProduct,
)
from typed_binance.spot.http.staking.soft.list import SoftStakingProduct

from tribulnation.binance.core import SdkMixin

EARN_URL = 'https://www.binance.com/earn'
"""Landing page for every Earn product family; Binance exposes no per-product URL."""

PAGE_SIZE = 100
"""Rows per page for the product-list cursors."""


def wanted(
  tags: Collection[InstrumentTag] | None, family: Sequence[InstrumentTag]
) -> bool:
  """Whether a product family can contribute under the requested tag filter."""
  return tags is None or bool(set(tags) & set(family))


def parse_flexible(product: FlexibleProduct) -> Instrument | None:
  """Map one Simple Earn flexible product onto an `Instrument`.

  Reports the flat `latestAnnualPercentageRate`. `tierAnnualPercentageRate` (an APR per
  balance bracket) is left out: it describes how the rate decays with position size, not
  separate instruments to subscribe to.
  """
  if product['isSoldOut'] or not product['canPurchase']:
    return None
  return Instrument(
    tags=['flexible'],
    asset=product['asset'],
    apr=product['latestAnnualPercentageRate'],
    min_qty=product['minPurchaseAmount'],
    url=EARN_URL,
    id=product['productId'],
  )


def parse_locked(product: LockedProduct) -> Instrument | None:
  """Map one Simple Earn locked product onto an `Instrument`.

  Products with no `detail.apr` are skipped: Binance's promotional "boost-only" listings
  carry only `extraRewardAsset`/`extraRewardAPR` on top of a base rate that does not
  exist for them, and reporting `apr=0` would describe them as zero-yield rather than as
  what they are.
  """
  detail = product['detail']
  base_apr = detail.get('apr')
  if detail['isSoldOut'] or base_apr is None:
    return None
  reward_asset = detail.get('rewardAsset')
  return Instrument(
    tags=['fixed'],
    asset=detail['asset'],
    apr=base_apr + (detail.get('extraRewardAPR') or 0),
    yield_asset=reward_asset if reward_asset != detail['asset'] else None,
    min_qty=product['quota']['minimum'],
    # This account's remaining subscription cap, not a venue-wide product maximum --
    # the closest thing Binance exposes.
    max_qty=product['quota']['totalPersonalQuota'],
    duration=timedelta(days=detail['duration']),
    url=EARN_URL,
    id=product['projectId'],
  )


def parse_soft_staking(product: SoftStakingProduct) -> Instrument:
  """Map one Soft Staking product onto an `Instrument`.

  `id` is left unset: Soft Staking has no per-product identifier, and is subscribed to
  with an account-wide on/off toggle rather than per product.
  """
  return Instrument(
    tags=['staking', 'flexible'],
    asset=product['asset'],
    apr=product['apr'],
    min_qty=product['minAmount'],
    max_qty=product['maxCap'],
    url=EARN_URL,
  )


def parse_on_chain_yields(product: OnChainYieldsLockedProduct) -> Instrument | None:
  """Map one On-chain Yields locked product onto an `Instrument`."""
  detail = product['detail']
  if detail['isSoldOut']:
    return None
  reward_asset = detail['rewardAsset']
  return Instrument(
    tags=['staking', 'fixed'],
    asset=detail['asset'],
    apr=detail['apr'],
    yield_asset=reward_asset if reward_asset != detail['asset'] else None,
    min_qty=product['quota']['minimum'],
    max_qty=product['quota']['totalPersonalQuota'],
    duration=timedelta(days=detail['duration']),
    url=EARN_URL,
    id=product['projectId'],
  )


@dataclass
class Instruments(SdkMixin, _Instruments):
  """Binance Earn instruments.

  Merges Simple Earn (flexible and locked), Soft Staking, On-chain Yields, BFUSD and
  RWUSD.

  **Does not support**:
  - ETH/SOL staking: neither exposes a product catalogue or a rate, only per-account
    quotas and holdings, so there is no `apr` to report.
  - Dual Investment: `product_list` has no filter-free listing mode, and a position
    settles in either the invested or the exercised asset depending on where spot lands
    at expiry, so neither `asset` nor `yield_asset` is knowable up front.
  - Mining and Yield Arena: hashrate payouts and giveaway promotions respectively,
    neither of which is a subscribed-amount-times-rate instrument.
  """

  @SDK.method
  async def flexible_instruments(self) -> list[Instrument]:
    """Fetch every available Simple Earn flexible product."""
    paging = self.client.spot.http.simple_earn.flexible.list_paged(size=PAGE_SIZE)
    state = paging.init
    out: list[Instrument] = []
    while state is not None:
      chunk, state = await self.call_binance(lambda: paging.next(state))  # type: ignore
      out.extend(i for p in chunk if (i := parse_flexible(p)) is not None)
    return out

  @SDK.method
  async def locked_instruments(self) -> list[Instrument]:
    """Fetch every available Simple Earn locked product."""
    paging = self.client.spot.http.simple_earn.locked.list_paged(size=PAGE_SIZE)
    state = paging.init
    out: list[Instrument] = []
    while state is not None:
      chunk, state = await self.call_binance(lambda: paging.next(state))  # type: ignore
      out.extend(i for p in chunk if (i := parse_locked(p)) is not None)
    return out

  @SDK.method
  async def soft_staking_instruments(self) -> list[Instrument]:
    """Fetch every available Soft Staking product."""
    paging = self.client.spot.http.staking.soft.list_paged(size=PAGE_SIZE)
    state = paging.init
    out: list[Instrument] = []
    while state is not None:
      chunk, state = await self.call_binance(lambda: paging.next(state))  # type: ignore
      out.extend(parse_soft_staking(p) for p in chunk)
    return out

  @SDK.method
  async def on_chain_yields_instruments(self) -> list[Instrument]:
    """Fetch every available On-chain Yields locked product."""
    paging = self.client.spot.http.staking.on_chain_yields.locked.list_paged(
      size=PAGE_SIZE
    )
    state = paging.init
    out: list[Instrument] = []
    while state is not None:
      chunk, state = await self.call_binance(lambda: paging.next(state))  # type: ignore
      out.extend(i for p in chunk if (i := parse_on_chain_yields(p)) is not None)
    return out

  @SDK.method
  async def bfusd_instruments(self) -> list[Instrument]:
    """Fetch BFUSD's current rate as a single flexible instrument.

    BFUSD has no product catalogue; its only rate is the newest `rate_history` row.
    """
    page = await self.call_binance(
      lambda: self.client.spot.http.bfusd.history.rate_history(size=1)
    )
    rows = page.get('rows') or []
    if not rows or (rate := rows[0].get('annualPercentageRate')) is None:
      return []
    return [
      Instrument(
        tags=['flexible'],
        asset='USDT',
        apr=rate,
        yield_asset='BFUSD',
        url=EARN_URL,
      )
    ]

  @SDK.method
  async def rwusd_instruments(self) -> list[Instrument]:
    """Fetch RWUSD's current rate, once per asset it can be subscribed with."""
    page = await self.call_binance(
      lambda: self.client.spot.http.rwusd.history.rate_history(size=1)
    )
    rows = page.get('rows') or []
    if not rows or (rate := rows[0].get('annualPercentageRate')) is None:
      return []
    return [
      Instrument(
        tags=['flexible'],
        asset=asset,
        apr=rate,
        yield_asset='RWUSD',
        url=EARN_URL,
      )
      for asset in ('USDT', 'USDC')
    ]

  @SDK.method
  async def instruments(
    self,
    *,
    tags: Collection[InstrumentTag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    """Fetch every Binance Earn instrument, filtered by tag and asset."""
    families: list[Coroutine[Any, Any, list[Instrument]]] = []
    if wanted(tags, ['flexible']):
      families.append(self.flexible_instruments())
      families.append(self.bfusd_instruments())
      families.append(self.rwusd_instruments())
    if wanted(tags, ['fixed']):
      families.append(self.locked_instruments())
    if wanted(tags, ['staking', 'flexible']):
      families.append(self.soft_staking_instruments())
    if wanted(tags, ['staking', 'fixed']):
      families.append(self.on_chain_yields_instruments())

    groups = await asyncio.gather(*families)
    out = [instrument for group in groups for instrument in group]
    if tags is not None:
      out = [i for i in out if set(i.tags) & set(tags)]
    if assets is not None:
      out = [i for i in out if i.asset in assets]
    return out
