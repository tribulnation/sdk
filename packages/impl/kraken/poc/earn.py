# %%
from decimal import Decimal
from datetime import timedelta
from typing_extensions import Collection

from typed_kraken import Kraken
from typed_kraken.spot.earn.strategies import EarnStrategy
from dotenv import load_dotenv

from tribulnation.sdk.earn.instruments import Instrument, InstrumentTag

load_dotenv()

client = await Kraken.new().__aenter__()

ASSETS = ['BTC', 'ETH', 'ADA']


# %% [markdown]
# ## `Instruments` -- earn strategies
#
# Kraken has a dedicated `spot.earn` namespace (`strategies`, `allocations`, `allocate`, `allocate_status`, `deallocate`, `deallocate_status`) that maps closely onto the abstract `Instruments` interface -- `spot.earn.strategies` is the discovery endpoint behind `instruments()`.

# %%
def to_tags(strategy: EarnStrategy) -> list[InstrumentTag]:
  tags: list[InstrumentTag] = []
  lock_type = strategy.get('lock_type') or {}
  lt = lock_type.get('type')
  if lt in ('instant', 'flex'):
    # 'instant' is what Kraken's UI calls "flexible" (no unbonding period).
    # 'flex' is account-wide Kraken Rewards -- also un-bonded, but can't be
    # manually allocated to (see coverage notes below).
    tags.append('flexible')
  elif lt == 'bonded':
    tags.append('fixed')
  yield_source = strategy.get('yield_source') or {}
  if yield_source.get('type') == 'staking':
    tags.append('staking')
  return tags


def to_duration(strategy: EarnStrategy) -> timedelta | None:
  lock_type = strategy.get('lock_type') or {}
  if lock_type.get('type') == 'bonded':
    bonding = lock_type.get('bonding_period') or 0
    unbonding = lock_type.get('unbonding_period') or 0
    return timedelta(seconds=bonding + unbonding)
  return None


def to_apr(strategy: EarnStrategy) -> Decimal:
  # Kraken's `apr_estimate.low`/`high` are percentage points (e.g. "2.5880" == 2.588%),
  # not fractions of 1 -- the SDK's `apr` wants a fraction (0.01 == 1%), so divide by 100.
  est = strategy.get('apr_estimate') or {}
  low = est.get('low')
  high = est.get('high')
  if low is not None and high is not None:
    return (low + high) / 2 / 100
  if low is not None:
    return low / 100
  if high is not None:
    return high / 100
  return Decimal(0)


async def instruments(
  *,
  tags: Collection[InstrumentTag] | None = None,
  assets: Collection[str] | None = None,
) -> list[Instrument]:
  result = await client.spot.earn.strategies()
  out: list[Instrument] = []
  for s in result.get('items') or []:
    inst = Instrument(
      tags=to_tags(s),
      asset=s.get('asset', ''),
      apr=to_apr(s),
      min_qty=s.get('user_min_allocation'),
      max_qty=s.get('user_cap'),
      duration=to_duration(s),
      id=s.get('id'),
    )
    if tags is not None and not any(t in inst.tags for t in tags):
      continue
    if assets is not None and inst.asset not in assets:
      continue
    out.append(inst)
  return out


await instruments(assets=ASSETS)

# %%
# Same call, exercising the `tags` filter (client-side -- see coverage notes).
await instruments(tags=['staking'])

# %% [markdown]
# ## Coverage
#
# **Fully supported, with caveats.** `spot.earn.strategies` returns everything `Instruments.instruments()` needs, but a few fields require interpretation rather than a direct copy:
#
# - `apr`: Kraken reports a `low`/`high` percentage-point range per strategy (not always distinct, e.g. `0.1000`/`0.1000` above); this notebook averages them and converts to the SDK's fraction-of-1 convention. A range collapses to one number, losing the low/high spread.
# - `tags`: Kraken's `lock_type` (`flex` / `bonded` / `instant`) and `yield_source` (`staking` / `off_chain` / `opt_in_rewards`) are the closest analogues to the SDK's `InstrumentTag`s, but the mapping is a judgment call -- `flex` ("Kraken Rewards", account-wide, `can_allocate: false`) is tagged `'flexible'` even though, unlike `instant`, it can't actually be manually (de)allocated. The SDK has no tag for 'not directly subscribable'.
# - `min_qty`/`max_qty`: the SDK docs these as asset quantities, but Kraken's `user_min_allocation` is denominated in USD and `user_cap` in the *native* asset -- two different units get shoehorned into the same two fields here.
# - `duration`: only meaningful for `bonded` strategies (`bonding_period + unbonding_period`); `instant`/`flex` strategies have no bonding, so `duration` is `None` for the large majority of instruments, which is arguably correct but worth flagging.
# - `url`: not provided by this endpoint at all -- always `None`.
#
# `assets`/`tags` filtering is done client-side after fetching every strategy: Kraken's own `asset`/`lock_type` request filters exist but only accept a single asset and a fixed lock-type enum respectively, not an arbitrary `Collection[str]`, so filtering post-fetch is simpler and just as correct for an account with this few strategies (paging is documented as not yet implemented server-side, so one request already returns everything).
