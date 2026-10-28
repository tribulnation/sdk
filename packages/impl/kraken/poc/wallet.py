# %%
from decimal import Decimal

from typed_kraken import Kraken
from dotenv import load_dotenv

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

load_dotenv()

client = await Kraken.new().__aenter__()

ASSETS = ['XBT', 'ETH', 'USDT']


# %% [markdown]
# ## `DepositMethods`
#
# Kraken's `spot.funding.deposit_methods` requires a single `asset` per call -- there is no "list every deposit method for every asset" mode, so `assets=None` ("give me everything") can't be honored directly; see coverage notes.

# %%
async def deposit_methods(*, assets: list[str] | None = None) -> list[DepositMethod]:
  # Kraken has no asset-less "all deposit methods" call; None falls back to a curated
  # demo list rather than silently returning nothing.
  assets = list(assets) if assets is not None else ASSETS
  out: list[DepositMethod] = []
  for asset in assets:
    raw = await client.spot.funding.deposit_methods(asset=asset)
    for m in raw:
      fee = m.get('fee')
      out.append(
        DepositMethod(
          asset=asset,
          # Kraken's "method" (e.g. "Bitcoin", "kBTC - Optimism (Unified)") is the closest
          # thing to a network identifier this endpoint returns.
          network=m['method'],
          fee=DepositMethod.Fee(asset=asset, amount=Decimal(fee)) if fee else None,
          contract_address=None,
          min_confirmations=None,
        )
      )
  return out


await deposit_methods(assets=ASSETS)


# %% [markdown]
# ## `WithdrawalMethods`
#
# Unlike deposits, `spot.funding.withdraw_methods` accepts an *optional* `asset`, so "every withdrawal method" is a real, single request here.

# %%
async def withdrawal_methods(
  *,
  assets: list[str] | None = None,
  networks: list[str] | None = None,
) -> list[WithdrawalMethod]:
  # Kraken's endpoint takes at most one asset/network per call; the SDK's plural
  # Collection[str] is honored by fanning out one request per asset when given.
  out: list[WithdrawalMethod] = []
  for asset in assets or [None]:
    for network in networks or [None]:
      raw = await client.spot.funding.withdraw_methods(asset=asset, network=network)
      for m in raw:
        fee = m.get('fee') or {}
        out.append(
          WithdrawalMethod(
            asset=m.get('asset', ''),
            network=m.get('network') or m.get('method', ''),
            fee=WithdrawalMethod.Fee(
              asset=fee.get('asset', m.get('asset', '')),
              amount=Decimal(fee['fee']),
            )
            if fee.get('fee') is not None
            else None,
            contract_address=None,
          )
        )
  return out


await withdrawal_methods()

# %%
# Same call, exercising the `assets` filter.
await withdrawal_methods(assets=['XXBT'])

# %% [markdown]
# ## Coverage
#
# **Partially supported**, and asymmetrically so between the two interfaces:
#
# - `WithdrawalMethods.withdrawal_methods` maps cleanly: Kraken's `withdraw_methods` already returns per-asset, per-network fee/method rows with an optional filter on either dimension, exactly matching the SDK's discovery semantics.
# - `DepositMethods.deposit_methods` is only partially supported: Kraken's `deposit_methods` endpoint requires a specific `asset` and returns no `network` field at all -- only a `method` name (`"Bitcoin"`, `"Bitcoin Lightning"`, `"kBTC - Optimism (Unified)"`, ...) that conflates network and delivery mechanism. There is no way to discover deposit methods for *all* assets in one call the way `withdrawal_methods` allows; a real integration would first enumerate assets via `spot.market_data.assets` and then issue one `deposit_methods` call per asset, which is expensive enough that this notebook demonstrates it against a small curated list (`ASSETS`) instead.
# - Neither Kraken endpoint returns `contract_address` or `min_confirmations` -- those SDK fields are always `None` here. Deposit addresses (with a contract/tag) only appear from the *separate* `spot.funding.deposit_addresses` endpoint, which requires picking one `method` first and isn't part of this abstract interface.
#
# `Wallet(WithdrawalMethods, DepositMethods)` itself adds no methods, and neither sub-interface declares a mutating (withdraw/transfer) method -- Kraken's `spot.funding.withdraw` exists but is out of scope here and was never called.
