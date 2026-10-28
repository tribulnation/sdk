# %%
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from typed_deribit import Deribit
from dotenv import load_dotenv

load_dotenv()

public_client = await Deribit.new(public=True).__aenter__()
client = await Deribit.new(testnet=True).__aenter__()

from tribulnation.sdk.earn.instruments import Instrument, InstrumentTag


# %% [markdown]
# > Authenticated calls below (`client`) run against the Deribit **TESTNET** account, not mainnet. Public/market-data calls use a public **mainnet** client (`public_client`) for representative data.

# %% [markdown]
# ## `Earn` -- no dedicated subscription-based earn product

# %% [markdown]
# Deribit has no Binance-style "Simple Earn" product family: no flexible/locked savings instruments with subscribe/redeem actions, min/max quantities, or fixed durations. The closest adjacent concept is Deribit's [yield reward-bearing coins](https://support.deribit.com/hc/en-us/articles/31424939199261-Yield-reward-bearing-coins) (`USDE`, `STETH`, `USDC`, `BUIDL`): holding a balance of one of these currencies earns a continuously-accruing reward, surfaced per-account via `private/get_reward_eligibility` (also mirrored, venue-wide, in `public/get_currencies`'s `apr` field). There is no action to "subscribe" -- the yield applies automatically to any held balance -- so the mapping below is approximate: `id`, `min_qty`/`max_qty`, `duration`, and `url` are all `None`, and every eligible currency is tagged `'flexible'` since there is no lock-up.

# %%
async def instruments(
  *, tags: list[InstrumentTag] | None = None, assets: list[str] | None = None,
) -> list[Instrument]:
  """Map Deribit's (account-scoped) yield-bearing-token reward APRs onto `Instrument`."""
  eligibility = await client.wallet.rewards.get_reward_eligibility()
  out: list[Instrument] = []
  for raw_asset, info in eligibility.items():
    asset = raw_asset.upper()
    # `eligibility_status` is documented as `eligible`/`non_eligible`, but the response only
    # ever lists the four yield-bearing coins and reported all four `eligible` on every run
    # here -- no live input produced a `non_eligible` row to check the branch against.
    if info['eligibility_status'] == 'non_eligible':
      continue
    if tags is not None and 'flexible' not in tags:
      continue
    if assets is not None and asset not in assets:
      continue
    out.append(Instrument(
      tags=['flexible'],
      asset=asset,
      apr=Decimal(str(info['apr_sma7'])) / 100,
    ))
  return out

await instruments()


# %% [markdown]
# ### Public, venue-wide APRs -- `public/get_apr_history`
#
# `instruments()` above reads `private/get_reward_eligibility`, so it needs credentials and reports the account's own 7-day SMA. `public/get_apr_history` publishes the same yield as a daily series for the four eligible coins, unauthenticated -- enough to build the same `Instrument` list from the public mainnet client, which is what `Earn.instruments` is documented as being for every venue where it exists at all. It also sidesteps the unrealistic testnet APRs the cell above surfaces, since there is nothing account-scoped about it.

# %%
from typing_extensions import Literal

APR_CURRENCIES: dict[str, Literal['usde', 'steth', 'usdc', 'buidl']] = {
  'USDE': 'usde', 'STETH': 'steth', 'USDC': 'usdc', 'BUIDL': 'buidl',
}


async def public_instruments(
  *, tags: list[InstrumentTag] | None = None, assets: list[str] | None = None,
) -> list[Instrument]:
  """Map Deribit's public, venue-wide yield APRs onto `Instrument`, without credentials."""
  if tags is not None and 'flexible' not in tags:
    return []
  out: list[Instrument] = []
  for asset, currency in APR_CURRENCIES.items():
    if assets is not None and asset not in assets:
      continue
    history = await public_client.market_data.get_apr_history(currency, limit=1)
    day = history['data'][0] if history['data'] else None
    if day is None or 'apr' not in day:
      continue
    out.append(Instrument(
      tags=['flexible'],
      asset=asset,
      apr=Decimal(str(day['apr'])) / 100,
    ))
  return out

await public_instruments()

# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **Partial.** `instruments()` executes live against the testnet account's reward eligibility and returns real data, but the underlying concept only loosely matches the `Earn` interface:
# - No discrete, subscribable "instrument": yield applies automatically to any held balance of an eligible currency, so `id`, `min_qty`, `max_qty`, `duration`, and `url` are all unavailable and left `None`.
# - Only 4 currencies are ever eligible (`USDE`, `STETH`, `USDC`, `BUIDL`): `private/get_reward_eligibility` returns those four keys and nothing else, and `public/get_apr_history` rejects any other currency outright (`-32602 Invalid params {'reason': 'invalid currency'}`). The `non_eligible` branch in the cell above is a documented status that no live response produced.
# - All four currencies reported `apr_sma7 = 0.0` on the testnet account at the time of this run -- genuine live testnet data, and no more representative of the real yield than any other testnet reward parameter would be. `public_instruments()` below reads the mainnet rates instead.
# - No subscribe/redeem/purchase action exists at all on this venue for these balances, so there is nothing analogous to `Earn`'s implied lifecycle beyond listing.
# - `public_instruments()` covers the same four coins from `public/get_apr_history` with no credentials at all, at mainnet rates (live: `USDE` 4.75%, `USDC` 3.4%, `BUIDL` 3.198%, `STETH` 2.245%).
