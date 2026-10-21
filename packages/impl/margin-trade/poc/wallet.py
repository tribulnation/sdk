# %% [markdown]
# # margin-trade `wallet` PoC
#
# Maps `typed_margin_trade` onto the SDK `wallet` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Testnet, signed by the master key (`MARGIN_TRADE_TESTNET_PRIVATE_KEY`, repo-root `.env`) for the deposit-address reads; mainnet history read by address through a credential-free client.

# %%
from typing_extensions import Collection, Sequence

from dotenv import dotenv_values
from sdk_dev.repo import repo_root
from typed_margin_trade import MarginTrade

from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod

env = dotenv_values(repo_root() / '.env')
client = await MarginTrade.new(env['MARGIN_TRADE_TESTNET_PRIVATE_KEY'], mainnet=False).__aenter__()
public = await MarginTrade.new(public=True).__aenter__()
SPOT_TRADER = 'HZEB64qX94oiDsKNisSxYSWuEaKdfsD4Rn1ZEToAw68a'

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(surface('typed_margin_trade', 'MarginTrade', grep=r'deposit|withdraw|coin|currenc|network|chain|onchain'))


# %% [markdown]
# ## `deposit_methods`
#
# Fetch the ways to deposit: one entry per asset and network. Not supported: no endpoint enumerates the (asset, chain) pairs. `getDepositAddress` answers for a pair the caller already names (the docs' USDC on `solana`, PRL on `pearl`), and `spotMeta` lists tokens without chains, so listing methods would mean hard-coding the docs' table.

# %%
async def deposit_methods(*, assets: Collection[str] | None = None) -> Sequence[DepositMethod]:
  raise NotImplementedError('margin.trade has no endpoint listing deposit assets and networks')


usdc = await client.user.get_deposit_address(asset='USDC', chain='solana')
prl = await client.user.get_deposit_address(asset='PRL', chain='pearl')
tokens = [t['name'] for t in (await client.info.spot_meta())['tokens']]
{'USDC': (usdc['asset'], usdc['chain'], len(usdc['depositAddress'])), 'PRL': (prl['asset'], prl['chain'], prl['depositAddress'][:5]), 'spotMeta tokens': tokens}


# %% [markdown]
# ## `withdrawal_methods`
#
# Fetch the ways to withdraw, with fees. Not supported: no endpoint lists withdrawal assets, networks or fees; the fee is known only after the fact, per withdrawal (`withdrawalHistory.withdraw_fee`: 1 USDC on testnet, 0.1 PRL on a mainnet account).

# %%
async def withdrawal_methods(*, assets: Collection[str] | None = None, networks: Collection[str] | None = None) -> Sequence[WithdrawalMethod]:
  raise NotImplementedError('margin.trade has no endpoint listing withdrawal methods or fees')


mine = (await client.info.withdrawal_history(client.account or ''))['withdrawals']
theirs = (await public.info.withdrawal_history(SPOT_TRADER))['withdrawals']
{(w['asset'], w['withdraw_fee']) for w in mine + theirs}

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `deposit_methods` | not supported | No endpoint enumerates deposit (asset, chain) pairs; `getDepositAddress` needs both named (USDC/`solana`, PRL/`pearl` verified on testnet) |
# | `withdrawal_methods` | not supported | No endpoint lists withdrawal assets, networks or fees; fees appear only per withdrawal in `withdrawalHistory` (1 USDC, 0.1 PRL) |

# %% [markdown]
# ## Catalogue
#
# Nothing to check: no method is implemented. The networks the deposit-address reads name (`solana`, `pearl`) are covered by the `report` PoC's catalogue cell, which sees them on history rows.

# %%
await client.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
await public.__aexit__(None, None, None)  # pyright: ignore[reportUnknownMemberType] -- upstream lifecycle parameters are untyped
