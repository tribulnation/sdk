"""Bit2Me implementation of the `instruments` earn endpoint."""

from typing_extensions import AsyncContextManager, Collection, Iterable, Sequence
from dataclasses import dataclass
import asyncio

from tribulnation.sdk.core import SDK
from tribulnation.sdk.earn.instruments import Instrument, Instruments as _Instruments
from tribulnation.bit2me.core import wrap_exceptions

from typed_bit2me import Bit2Me
from typed_bit2me.api.v2.earn.apy import Extra
from typed_bit2me.api.v2.earn.assets import Entry

BIT2ME_EARN_URL = 'https://bit2me.com/suite/earn'


def parse_asset(entry: Entry, apy: dict[str, Extra]) -> Iterable[Instrument]:
  """Build the earn instruments allowed for one `assets()` entry.

  Bit2Me pays rewards in one of a few reward currencies per asset (e.g. the
  asset itself, or B2M), each with its own frequency and yield. `entry`'s
  `currenciesRewardAllowed` is the authoritative list of those options, and
  each option's `extraYield` is added on top of the base rate from `apy`.

  This is the level-0 (no Space Center bonus) and no-lock-period rate: Bit2Me
  also boosts APR by account-wide staking level and, for some assets, by
  locking funds for a fixed period -- neither is exposed by a documented
  endpoint, so neither is reflected here.
  """
  if entry.get('disabled') or (asset := entry.get('currency')) is None:
    return
  rates = apy.get(asset, {})
  for reward in entry.get('currenciesRewardAllowed', []):
    reward_type = reward.get('type')
    reward_asset = reward.get('currency')
    if reward_type is None or (base := rates.get(reward_type)) is None:
      continue
    apr = base + reward.get('extraYield', 0)
    yield Instrument(
      tags=['flexible'],
      asset=asset,
      apr=apr,
      yield_asset=reward_asset if reward_asset and reward_asset != asset else None,
      url=BIT2ME_EARN_URL,
    )


@dataclass(frozen=True)
class Instruments(_Instruments):
  """Bit2Me implementation of `Instruments`, backed by the public earn endpoints."""

  client: Bit2Me

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    public: bool = True,
    validate: bool = True,
  ):
    """Construct an `Instruments` client.

    Args:
      api_key: Bit2Me API key. Unneeded: `instruments` only calls public endpoints.
      api_secret: Bit2Me API secret. Unneeded: `instruments` only calls public endpoints.
      public: Build a public-only client when no credentials are given.
      validate: Validate responses.
    """
    return cls(
      client=Bit2Me.new(
        api_key=api_key, api_secret=api_secret, public=public, validate=validate
      )
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.client

  @SDK.method
  @wrap_exceptions
  async def instruments(
    self,
    *,
    tags: Collection[Instrument.Tag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    entries, apy = await asyncio.gather(
      self.client.v2.earn.assets(), self.client.v2.earn.apy()
    )
    out: list[Instrument] = []
    for entry in entries:
      if assets is not None and entry.get('currency') not in assets:
        continue
      for inst in parse_asset(entry, apy):
        if tags is None or set(inst.tags).issubset(tags):
          out.append(inst)
    return out
