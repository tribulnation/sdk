"""Kraken implementation of the `instruments` earn endpoint, over `Earn/Strategies`."""

from typing_extensions import Collection, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from tribulnation.sdk.core import SDK
from tribulnation.sdk.earn.instruments import Instrument, Instruments as _Instruments
from tribulnation.kraken.core import AssetNames, Mixin, internal_ids

from typed_kraken.spot.earn.strategies import EarnStrategy


def parse_tags(strategy: EarnStrategy) -> list[Instrument.Tag]:
  """Read a strategy's tags off its lock type and yield source.

  `instant` is what Kraken's UI calls flexible: allocated and deallocated at will.
  `flex` is account-wide Kraken Rewards on eligible spot balances -- also unbonded,
  but switched on from the UI rather than allocated to (`can_allocate` is false);
  the SDK has no tag for that, so it is `flexible` too. `bonded` strategies carry an
  unbonding period and are `fixed`.
  """
  tags: list[Instrument.Tag] = []
  lock = strategy['lock_type'].get('type')
  if lock in ('instant', 'flex'):
    tags.append('flexible')
  elif lock == 'bonded':
    tags.append('fixed')
  if (strategy.get('yield_source') or {}).get('type') == 'staking':
    tags.append('staking')
  return tags


def parse_duration(strategy: EarnStrategy) -> timedelta | None:
  """The bonding plus unbonding period of a `bonded` strategy; `None` otherwise."""
  lock = strategy['lock_type']
  if lock.get('type') != 'bonded':
    return None
  return timedelta(
    seconds=lock.get('bonding_period', 0) + lock.get('unbonding_period', 0)
  )


def parse_apr(strategy: EarnStrategy) -> Decimal | None:
  """The midpoint of Kraken's estimated APR range, as a fraction of 1.

  `apr_estimate` is a `low`/`high` pair in percentage points (`2.5880` is 2.588%).
  The two are equal on most strategies; where they differ, the range collapses to
  its midpoint and the spread is lost. A strategy quoting no estimate has no APR.
  """
  estimate = strategy.get('apr_estimate')
  if estimate is None:
    return None
  low = estimate.get('low')
  high = estimate.get('high')
  if low is not None and high is not None:
    return (low + high) / 2 / 100
  if low is not None:
    return low / 100
  if high is not None:
    return high / 100
  return None


def parse_instrument(strategy: EarnStrategy, names: AssetNames) -> Instrument | None:
  """Map one strategy onto an `Instrument`, or skip one quoting no APR.

  `max_qty` is `user_cap`, in the native asset. `min_qty` is left unset:
  `user_min_allocation` is denominated in USD, not in the asset, so it cannot fill a
  field the SDK defines as an asset quantity. `Earn/Strategies` names assets by
  display name (`BTC`); the id emitted is the internal one every other surface
  uses (`XXBT`), through the venue's own `Assets` join.

  Args:
    strategy: The strategy row.
    names: Display name to internal id, from `internal_ids`.
  """
  apr = parse_apr(strategy)
  asset = strategy.get('asset')
  if apr is None or asset is None:
    return None
  return Instrument(
    tags=parse_tags(strategy),
    asset=names.get(asset, asset),
    apr=apr,
    max_qty=strategy.get('user_cap'),
    duration=parse_duration(strategy),
    id=strategy.get('id'),
  )


@dataclass(frozen=True, kw_only=True)
class Instruments(_Instruments, Mixin):
  """Kraken implementation of `Instruments`.

  `Earn/Strategies` needs a valid API key (no particular permission) and answers
  only the strategies available in the account's region, so there is no public
  form of this surface. Paging is documented as not implemented server-side: one
  request returns every strategy, and both filters are applied here.
  """

  @SDK.method
  async def strategies(self) -> Sequence[EarnStrategy]:
    """Fetch every earn strategy available to the account."""
    result = await self.call_kraken(self.client.spot.earn.strategies)
    return result.get('items') or []

  async def instruments(
    self,
    *,
    tags: Collection[Instrument.Tag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    names = await self.call_kraken(lambda: internal_ids(self.client))
    out: list[Instrument] = []
    for strategy in await self.strategies():
      instrument = parse_instrument(strategy, names)
      if instrument is None:
        continue
      if assets is not None and instrument.asset not in assets:
        continue
      if tags is not None and not set(instrument.tags) & set(tags):
        continue
      out.append(instrument)
    return out
