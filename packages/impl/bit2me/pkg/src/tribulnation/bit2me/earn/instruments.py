"""Bit2Me implementation of the `instruments` earn endpoint."""

from typing_extensions import Any, Collection, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
import asyncio

from tribulnation.sdk.earn.instruments import Instrument, Instruments as _Instruments
from tribulnation.bit2me.core import Mixin

from typed_bit2me.v2.earn.apy import EarnApyV2Response
from typed_bit2me.v2.earn.assets import Entry

BIT2ME_EARN_URL = 'https://bit2me.com/suite/earn'


def parse_asset(entry: Entry, apy: EarnApyV2Response) -> Iterable[Instrument]:
  """Build the earn instruments allowed for one `assets()` entry.

  Bit2Me pays rewards in one of a few reward currencies per asset (e.g. the
  asset itself, or B2M), each with its own frequency and yield. `entry`'s
  `currenciesRewardAllowed` is the authoritative list of those options, and
  each option's `extraYield` is added on top of the base rate from `apy`.

  This is the level-0 (no Space Center bonus) and no-lock-period rate. Bit2Me
  also boosts APR by account-wide staking level and, for B2M, by locking funds
  for 3/6/12 months, but `apy()` quotes one base yield per reward frequency and
  nothing per lock period, and the account's own level has no endpoint at all --
  so neither boost is derivable here, and every instrument comes out `flexible`.

  Args:
    entry: One `v2/earn/assets` row.
    apy: The whole `v2/earn/apy` table, keyed by subscription currency.
  """
  if entry.get('disabled') or (asset := entry.get('currency')) is None:
    return
  rates = apy.get(asset)
  for reward in entry.get('currenciesRewardAllowed', []):
    reward_type = reward.get('type')
    if rates is None or reward_type is None or (base := rates.get(reward_type)) is None:
      continue
    reward_asset = reward.get('currency')
    yield Instrument(
      tags=['flexible'],
      asset=asset,
      apr=Decimal(str(base)) + Decimal(str(reward.get('extraYield', 0))),
      yield_asset=reward_asset if reward_asset and reward_asset != asset else None,
      url=BIT2ME_EARN_URL,
    )


@dataclass(frozen=True, kw_only=True)
class Instruments(_Instruments, Mixin):
  """Bit2Me implementation of `Instruments`, backed by the public earn endpoints."""

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    public: bool = True,
    validate: bool = True,
    **fields: Any,
  ):
    """Construct an `Instruments` client.

    Both `v2/earn/assets` and `v2/earn/apy` are public, so this defaults to a
    credential-free client rather than refusing to build without an API key.

    Args:
      api_key: Bit2Me API key. Unneeded: `instruments` only calls public endpoints.
      api_secret: Bit2Me API secret. Unneeded, for the same reason.
      public: Build a public-only client when no credentials are given.
      validate: Validate responses.
      **fields: Any other field this surface declares.
    """
    return super().new(api_key, api_secret, public=public, validate=validate, **fields)

  async def instruments(
    self,
    *,
    tags: Collection[Instrument.Tag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    entries, apy = await asyncio.gather(
      self.call_bit2me(self.client.v2.earn.assets),
      self.call_bit2me(self.client.v2.earn.apy),
    )
    out: list[Instrument] = []
    for entry in entries:
      if assets is not None and entry.get('currency') not in assets:
        continue
      for instrument in parse_asset(entry, apy):
        if tags is None or set(instrument.tags) & set(tags):
          out.append(instrument)
    return out
