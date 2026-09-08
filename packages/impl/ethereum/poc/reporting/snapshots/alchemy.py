# %%
import os
from decimal import Decimal
from typing_extensions import Collection

from dotenv import load_dotenv
from web3 import Web3
from typed_alchemy import Alchemy
from typed_alchemy.portfolio.tokens import Token

from tribulnation.sdk.reporting import (
  Balances,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
  source_id,
)

load_dotenv()

NETWORK = 'arb-mainnet'
client = Alchemy.new()
await client.__aenter__()
address = os.environ['EVM_ADDRESS']

# %% [markdown]
# > This notebook hand-maps `typed_alchemy`'s raw responses onto `tribulnation.sdk.reporting`
# > types directly -- it does not import or call `tribulnation.ethereum` at all. Every
# > balance below is the **live, real** holdings of `EVM_ADDRESS`
# > (`0xE089aB95D28aCA5804a2F99c2cc259A88d3Be799`) on **Arbitrum One**, read through
# > Alchemy's Portfolio API.
# >
# > **Why Arbitrum One, not Ethereum mainnet.** `sdk.test.toml` reuses the same
# > `EVM_ADDRESS` across eight EVM venues, so the network is a choice, not a given. Checked
# > live before writing: Alchemy reports 30 fungible rows / 17 non-zero on `arb-mainnet`
# > against 16 / 9 on `eth-mainnet`, and -- the reason that matters here -- Arbitrum is the
# > only one of the two where the address holds tokens whose metadata reports **0
# > decimals**. That is the exact input that breaks a `decimals or 18` fallback, so mapping
# > against Ethereum mainnet would have left the branch untested.
# >
# > Out of scope: `Snapshots.snapshot()` is the only method on this surface, so there is
# > nothing else to map. Alchemy also returns USD prices per token (requested below, and
# > visible in the raw rows), but `Snapshot`/`SubaccountSnapshot` carry no price or
# > valuation field, so prices are fetched and then dropped -- see the coverage notes.

# %% [markdown]
# ## `Snapshots`

# %%
NATIVE_ASSET = 'native'
"""How the SDK's EVM impls label the chain's gas token in a `balances` dict."""
NATIVE_DECIMALS = 18


def raw_balance(token: Token) -> int:
  """Parse Alchemy's `tokenBalance`, a 0x-prefixed 32-byte hex integer."""
  value = token['tokenBalance']
  return int(value, 16) if value.startswith('0x') else int(value)


def token_decimals(token: Token) -> int | None:
  """Return the row's declared decimals, or `None` when Alchemy reports none."""
  metadata = token.get('tokenMetadata')
  return None if metadata is None else metadata.get('decimals')


def token_amount(token: Token) -> Decimal:
  """Convert one portfolio row's raw balance into display units.

  The native row carries no `tokenMetadata` at all, so its decimals are `None` and 18 is
  the right default. A token that genuinely declares `0` decimals is a different case
  and must keep its raw integer -- hence `is None` rather than `decimals or 18`, which
  would divide a 0-decimal balance by 10**18 and report it as dust.
  """
  decimals = token_decimals(token)
  if decimals is None:
    decimals = NATIVE_DECIMALS
  return Decimal(raw_balance(token)) * (Decimal(10) ** -decimals)


# %%
async def portfolio_tokens() -> list[Token]:
  """Fetch every fungible balance Alchemy reports for the address on `NETWORK`.

  `tokens_paged` is awaitable and flattens every page, so this is the whole holdings
  set, not a first page.
  """
  return list(
    await client.portfolio.tokens_paged(
      [{'address': address, 'networks': [NETWORK]}],
      with_metadata=True,
      with_prices=True,
      include_native_tokens=True,
      include_erc20tokens=True,
    )
  )


tokens = await portfolio_tokens()
held = [token for token in tokens if raw_balance(token) > 0]
len(tokens), len(held)

# %%
# The native row: `tokenAddress` is null and there is no metadata, so `token_decimals`
# returns None and `token_amount` falls back to 18.
native = [token for token in tokens if token['tokenAddress'] is None]
[(token['network'], token_decimals(token), token_amount(token)) for token in native]

# %%
# The branch a `decimals or 18` fallback gets wrong, checked against the *whole* holdings
# set rather than a hand-picked list: every row Alchemy reports with `decimals == 0` and
# a non-zero balance. `token_amount` must return the raw integer for each of these.
zero_decimal = [token for token in held if token_decimals(token) == 0]
[
  (
    token['tokenAddress'],
    (token.get('tokenMetadata') or {}).get('symbol'),
    raw_balance(token),
    token_amount(token),
  )
  for token in zero_decimal
]


# %%
async def snapshot(assets: Collection[str] | None = None) -> SnapshotRecord:
  """Map Alchemy's portfolio rows onto a `SnapshotRecord`.

  Alchemy enumerates holdings itself, so `assets` only narrows what is already there --
  it never triggers an extra lookup, and an asset the address does not hold is simply
  absent rather than reported as zero.

  Args:
    assets: Contract addresses (any casing) or `'native'` to keep. All holdings when
      omitted.
  """
  wanted = (
    None
    if assets is None
    else {
      NATIVE_ASSET if asset == NATIVE_ASSET else Web3.to_checksum_address(asset)
      for asset in assets
    }
  )
  balances = Balances()
  for token in await portfolio_tokens():
    contract = token['tokenAddress']
    asset = NATIVE_ASSET if contract is None else Web3.to_checksum_address(contract)
    if wanted is not None and asset not in wanted:
      continue
    amount = token_amount(token)
    if amount != 0:
      balances[asset] += amount
  return SnapshotRecord(
    snapshot=Snapshot(subaccounts=[SubaccountSnapshot(balances=balances)]),
    provenance={'source': 'api', 'service': 'alchemy', 'id': source_id('alchemy')},
  )


await snapshot()

# %%
# The `assets` narrowing, against real holdings: USDC (6 decimals), one of the
# 0-decimal spam tokens found above, and the native gas token.
await snapshot(
  [
    NATIVE_ASSET,
    '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
    '0x42c35B14E6f163eA0A625c919Dd95F5A3A594C19',
  ]
)

# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **`Snapshots.snapshot()` -- fully backed by `typed_alchemy`, live.** One call
# (`portfolio.tokens_paged`) enumerates the native balance and every ERC-20 balance in a
# single request, with the metadata needed to scale each one, so nothing here needs a
# second provider or an asset list supplied by the caller. `snapshot()` ran live and
# returned 17 real non-zero balances on Arbitrum One, including the native gas token.
#
# **What Alchemy backs, and what it does not.** `SubaccountSnapshot.balances` maps
# cleanly. `SubaccountSnapshot.positions` has no Alchemy counterpart -- an EVM address has
# no venue-side derivative positions, so a single unnamed subaccount with balances only is
# the honest shape, and `Snapshot.subaccounts` is a one-element list. `Snapshot.time` is
# left at its default (now), which is right: the Portfolio API reports current state and
# returns no block number to pin the read to. Alchemy's per-token USD prices are requested
# above and visible in the raw rows, but neither `Snapshot` nor `SubaccountSnapshot` has
# anywhere to put a price, so they are dropped.
#
# **A real bug in `tribulnation.ethereum.reporting.snapshots.alchemy`, confirmed live.**
# That module's `token_qty` scales with
#
# ```python
# Decimal(hex_balance(value)) * (Decimal(10) ** -(decimals or NATIVE_DECIMALS))
# ```
#
# `decimals or NATIVE_DECIMALS` treats a declared `0` the same as a missing one. The
# zero-decimal cell above lists the rows this address actually holds on Arbitrum with
# `decimals == 0` and a non-zero balance (5 of them at the time of this run): the impl
# reports each of those as `5E-18`-scale dust instead of the integer count. The fix is the
# `is None` test used here. The same shape appears in `snapshots/moralis.py`
# (`int(token.get('decimals') or 0)` -- harmless there, since the fallback happens to be
# `0`) and in the Etherscan history mapping, so it is worth a sweep rather than a one-line
# patch.
#
# **Also worth noting for the impl:** `AlchemySnapshots.snapshot()` calls
# `self.alchemy.portfolio.tokens.paged(...)` and pages it with `paging.init` /
# `paging.next(state)`. In `typed_alchemy` 2.0.1 that method is
# `portfolio.tokens_paged(addresses, *, with_metadata=..., ...)` -- a flat method taking
# keyword arguments, not a `tokens.paged(request_dict)` -- so the impl does not run
# against the installed client at all. Its `ignore_zero_value` default also drops zero
# balances, which this notebook reproduces (`amount != 0`).
