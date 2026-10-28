# %%
import asyncio
import os
from decimal import Decimal

from typed_hyperliquid import Hyperliquid
from dotenv import load_dotenv

from tribulnation.sdk.earn.instruments import Instrument

load_dotenv()

client = await Hyperliquid.new(mainnet=False, public=True).__aenter__()
ADDRESS = os.environ['HYPERLIQUID_TESTNET_ADDRESS']

ASSETS = ['USDC', 'HYPE']

ADDRESS


# %% [markdown]
# > `client` is the raw `typed_hyperliquid.Hyperliquid` client, hand-mapped onto `tribulnation.sdk.earn` below -- no production `tribulnation.hyperliquid` code is imported or driven (the production package currently has no `earn` module at all; see the task notes). Runs against the same Hyperliquid **testnet** account as `market.ipynb`/`reporting.ipynb`.
# >
# > Hyperliquid's yield-bearing surfaces are: a spot-token **borrow/lend money market** (`allBorrowLendReserveStates` -- fully enumerable, live supply APR per token), **vaults** (`userVaultEquities`/`vaultDetails` -- live APR, but only for vaults this account already holds equity in; there is no "list every vault" endpoint), and native **HYPE staking** (delegation-based, no queryable APR at all). Only the first two map cleanly onto `Instrument` (which requires a real `apr`); staking is covered separately below as an account-scoped supplementary read, not folded into `instruments()`.

# %% [markdown]
# ## `Earn` (`Instruments`)

# %%
async def lending_instruments(*, assets: list[str] | None = None) -> list[Instrument]:
  spot_meta, _ = await client.info.spot_meta_and_asset_ctxs()
  tokens_by_index = {t['index']: t for t in spot_meta['tokens']}
  reserves = await client.info.all_borrow_lend_reserve_states()
  out: list[Instrument] = []
  for token_idx, state in reserves:
    token = tokens_by_index[token_idx]
    if assets is not None and token['name'] not in assets:
      continue
    out.append(
      Instrument(
        tags=['flexible'],
        asset=token['name'],
        apr=Decimal(state['supplyYearlyRate']),
      )
    )
  return out


# Real data: every spot token with an active borrow/lend reserve on testnet.
result = await lending_instruments()
len(result), result

# %%
await lending_instruments(assets=ASSETS)


# %%
async def vault_instruments() -> list[Instrument]:
  # Only vaults this account already has equity in are enumerable this way -- typed_hyperliquid
  # has no "list every vault" endpoint, so full discovery isn't possible (see coverage note below).
  equities = await client.info.user_vault_equities(user=ADDRESS)
  out: list[Instrument] = []
  for eq in equities:
    details = await client.info.vault_details(
      user=ADDRESS, vault_address=eq['vaultAddress']
    )
    if details is None:
      continue
    out.append(
      Instrument(
        tags=['flexible'],
        asset='USDC',
        apr=Decimal(str(details['apr'])),
        id=eq['vaultAddress'],
      )
    )
  return out


# Empty and accurate: this testnet account holds equity in no vaults.
await vault_instruments()


# %% [markdown]
# ### `instruments(*, tags=None, assets=None)`

# %%
async def instruments(
  *,
  tags: list[str] | None = None,
  assets: list[str] | None = None,
) -> list[Instrument]:
  results = await asyncio.gather(lending_instruments(), vault_instruments())
  out = [ins for group in results for ins in group]
  if assets is not None:
    out = [ins for ins in out if ins.asset in assets]
  if tags is not None:
    out = [ins for ins in out if set(ins.tags) & set(tags)]
  return out


await instruments(assets=ASSETS)

# %% [markdown]
# ### Coverage assessment: `Instruments`
#
# **Partial, but the covered part is fully live-tested.** The borrow/lend money market maps cleanly onto `Instrument` and is executed live above -- real per-token supply APRs for every spot token with an active reserve on testnet, unfiltered and filtered by `assets`. Vaults also map cleanly (via `vaultDetails.apr`), but `vault_instruments()` can only enumerate vaults this account already holds equity in (an empty, accurate result here) -- `typed_hyperliquid` has no "list every vault" / vault-leaderboard endpoint, so a real integration would need an external vault registry to discover new ones.
#
# **Not covered**: native HYPE staking has no queryable APR anywhere in `typed_hyperliquid` (`staking_summary`/`staking_delegations`/`staking_history`/`staking_rewards` below all report real state, but none of them -- nor any other endpoint found -- returns a rate), and `Instrument.apr` is a required field, so staking can't be honestly folded into `instruments()` without fabricating a number. It's covered instead as an account-scoped supplementary read below, matching the venue's actual query surface rather than papering over the gap.

# %% [markdown]
# ## Account-scoped supplementary reads (not part of the abstract interface)

# %%
await client.info.staking_summary(user=ADDRESS)

# %%
await client.info.staking_delegations(user=ADDRESS)

# %%
await client.info.staking_history(user=ADDRESS)

# %%
await client.info.staking_rewards(user=ADDRESS)

# %%
await client.info.borrow_lend_user_state(user=ADDRESS)


# %% [markdown]
# ## Deposit / delegate / redeem (state-mutating -- written, never executed)

# %%
async def stake(amount_wei: int, *, chain_id: str = '0xa4b1'):
  # 0xa4b1 = Arbitrum -- the EIP-712 signing-domain chain id `typed_hyperliquid` docstrings
  # use for every user-signed action, independent of whether the API itself is testnet/mainnet
  # (that's controlled separately, by how `client` was constructed).
  return await client.exchange.staking_deposit(
    wei=amount_wei, signature_chain_id=chain_id
  )


# Not executed here -- would move real (test) funds from spot into staking on the testnet account.
await stake(1_000_000_000_000_000_000)  # 1 HYPE, in wei (18 decimals)


# %%
async def delegate(
  validator: str,
  amount_wei: int,
  *,
  is_undelegate: bool = False,
  chain_id: str = '0xa4b1',
):
  return await client.exchange.token_delegate(
    validator=validator,
    is_undelegate=is_undelegate,
    wei=amount_wei,
    signature_chain_id=chain_id,
  )


# Not executed here -- would delegate real (test) staked HYPE to a validator, or undelegate it.
await delegate('0x0000000000000000000000000000000000000000', 1_000_000_000_000_000_000)


# %%
async def unstake(amount_wei: int, *, chain_id: str = '0xa4b1'):
  return await client.exchange.staking_withdraw(
    wei=amount_wei, signature_chain_id=chain_id
  )


# Not executed here -- would start the 7-day unstaking queue on the testnet account.
await unstake(1_000_000_000_000_000_000)


# %%
async def vault_deposit(vault_address: str, usd: float, *, is_deposit: bool = True):
  return await client.exchange.vault_transfer(
    vault_address=vault_address,
    is_deposit=is_deposit,
    usd=usd,
  )


# Not executed here -- would deposit (or withdraw) real (test) USDC from a real vault.
await vault_deposit('0x0000000000000000000000000000000000000000', 10.0)
