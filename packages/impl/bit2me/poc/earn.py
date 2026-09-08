# %%
from decimal import Decimal
import asyncio

from typed_bit2me import Bit2Me
from dotenv import load_dotenv

from tribulnation.sdk.earn.instruments import Instrument

load_dotenv()

client = await Bit2Me.new().__aenter__()

ASSETS = ['BTC', 'ETH', 'USDT', 'B2M']


# %% [markdown]
# ## `Earn` (`Instruments`)
#
# Bit2Me's Earn surface is two public endpoints, combined client-side: `v2.earn.assets()` lists every Earn-eligible asset with its allowed reward currencies (`currenciesRewardAllowed`, each with a reward `type` -- `daily`/`weekly`/`monthly`) and lock periods, while `v2.earn.apy()` gives the base annual yield per currency, broken down by that same `daily`/`weekly`/`monthly` key. Neither call needs credentials.

# %%
async def instruments(
  *,
  tags: list[str] | None = None,
  assets: list[str] | None = None,
) -> list[Instrument]:
  entries, apy = await asyncio.gather(client.v2.earn.assets(), client.v2.earn.apy())
  out: list[Instrument] = []
  for entry in entries:
    asset = entry.get('currency')
    if entry.get('disabled') or asset is None:
      continue
    if assets is not None and asset not in assets:
      continue
    rates = apy.get(asset)
    for reward in entry.get('currenciesRewardAllowed', []):
      reward_type = reward.get('type')
      base = rates.get(reward_type) if rates and reward_type else None
      if base is None:
        continue
      reward_asset = reward.get('currency')
      apr = Decimal(str(base)) + Decimal(str(reward.get('extraYield', 0)))
      inst = Instrument(
        tags=['flexible'],
        asset=asset,
        apr=apr,
        yield_asset=reward_asset if reward_asset and reward_asset != asset else None,
        url='https://bit2me.com/suite/earn',
      )
      if tags is None or set(inst.tags) & set(tags):
        out.append(inst)
  return out


await instruments(assets=ASSETS)

# %%
# Every instrument this mapping produces is tagged 'flexible' only. Lock periods do exist
# in the data -- `assets()`'s `lockPeriodsAllowed` lists 3/6/12 months, but for exactly
# one asset (B2M, Bit2Me's own farming pool); every other entry's list is empty. What's
# missing is the rate: `apy()` quotes one base yield per reward frequency and nothing
# per lock period, so a 'fixed' instrument's APR isn't derivable. Account staking level
# has no endpoint at all (`levelExtraYieldPercentage` on an entry is the asset's share of
# the level bonus, not the account's tier). Same conclusion as
# `tribulnation/bit2me/earn/instruments.py`'s `parse_asset` docstring, which this
# notebook's `instruments()` re-derives independently rather than importing. The `tags`
# filter itself works correctly; there's just nothing else in the data for it to match.
await instruments(tags=['fixed'])

# %%
# Unfiltered call against the live catalogue -- large (Bit2Me lists ~500 assets total,
# though only a subset are Earn-eligible), so just reporting the count and a sample.
all_instruments = await instruments()
len(all_instruments), all_instruments[:5]


# %% [markdown]
# ## Subscribe / redeem (state-mutating -- written, never executed)
#
# `v1.earn.movements.create()` isn't part of the abstract `Instruments` interface (it's
# read-only), but is the natural next step a real integration would need: one endpoint,
# discriminated by `type: 'deposit' | 'withdrawal'`, for both subscribing to and redeeming
# from an Earn position. Included here only to show the mapping -- **never executed**.

# %%
async def subscribe(instrument: Instrument, *, amount: Decimal) -> str:
  result = await client.v1.earn.movements.create(
    currency=instrument.asset,
    amount=str(amount),
    type='deposit',
  )
  return result['movementId']


# Not executed here -- would move real funds into a real Earn position.
await subscribe(
  Instrument(tags=['flexible'], asset='USDT', apr=Decimal('0.01')),
  amount=Decimal('1'),
)


# %%
async def redeem(*, asset: str, amount: Decimal) -> str:
  result = await client.v1.earn.movements.create(
    currency=asset,
    amount=str(amount),
    type='withdrawal',
  )
  return result['movementId']


# Not executed here -- would redeem a real Earn holding.
await redeem(asset='USDT', amount=Decimal('1'))

# %% [markdown]
# ## Coverage
#
# **Fully supported.** `instruments()` is the entire abstract `Earn`/`Instruments`
# interface, and Bit2Me's two public Earn endpoints cover it completely -- no credentials
# needed. Both filters work as documented:
#
# - `assets`: filters `assets()` entries by subscription currency before mapping,
#   exercised above with `['BTC', 'ETH', 'USDT', 'B2M']`. Only three of those four show up
#   in the result: USDT is one of the 17 entries `assets()` currently returns with
#   `disabled: true`, and disabled entries are dropped before mapping.
# - `tags`: filters the mapped `Instrument`s client-side. Every instrument Bit2Me currently
#   exposes is tagged `'flexible'`, so `'fixed'`/`'staking'`/etc. never appear. That's a
#   data-shape gap rather than a bug in the filter: `assets()`'s `lockPeriodsAllowed` does
#   list 3/6/12-month locks for B2M (and for no other asset), but `apy()` quotes one base
#   yield per reward frequency and nothing per lock period, so a locked instrument's actual
#   boosted APR isn't derivable from these two endpoints. The account-wide staking level
#   that also boosts the rate has no endpoint at all.
#
# `assets()` additionally takes a `type` filter (`'partner'` | `'farming-pool'`), which
# splits the same catalogue 56/2 rather than exposing anything new -- the two farming-pool
# entries are B2M and B3X. Nothing in it maps to an `Instrument` field, so it isn't used
# above.
#
# `v1.earn.movements.create()` (subscribe/redeem) is written above but not part of the
# abstract interface and not executed.
