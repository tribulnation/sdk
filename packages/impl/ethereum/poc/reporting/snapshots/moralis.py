# %%
import os
from decimal import Decimal
from typing_extensions import Collection

from dotenv import load_dotenv
from web3 import Web3
from typed_moralis import AuthError, Moralis
from typed_moralis.evm.wallet.token_balances import TokenBalance

from tribulnation.sdk.reporting import (
  Balances,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
  source_id,
)

load_dotenv()

CHAIN = 'arbitrum'
client = Moralis.new()
await client.__aenter__()
address = os.environ['EVM_ADDRESS']


# %% [markdown]
# > **This notebook did not get live data. The Moralis account behind `MORALIS_API_KEY` is
# > out of quota**, and every Deep Index endpoint answers `401` with
# > `"Your Moralis Free usage is paused. Upgrade to a paid plan to resume usage."` The next
# > cell shows that response, unedited, straight off the wire. It is an account-billing
# > state, not a bad key and not a client bug: the same 401 comes back from a raw `httpx`
# > GET to `https://deep-index.moralis.io/api/v2.2/wallets/<address>/tokens` with the same
# > header.
# >
# > So the mapping below is derived from `typed_moralis` 0.2.1's **declared response
# > models**, not from observed responses, and it is not verified. Every place where the
# > model leaves something ambiguous is called out inline rather than guessed at silently,
# > and the last cell, which runs the mapping, is left unexecuted until the account has
# > quota. Nothing here should be read as "this works" -- only as "this is what
# > the declared contract supports, and here is exactly which parts a live run would still
# > have to settle".
# >
# > Network: **Arbitrum One**, matching the Alchemy and node notebooks next to this one --
# > `EVM_ADDRESS` holds 17 non-zero balances there against 9 on Ethereum mainnet, including
# > the 0-decimal tokens that make the decimals branch worth testing.

# %%
async def credentials_check() -> object:
  """Call the cheapest Deep Index endpoint and report what comes back."""
  try:
    return await client.evm.wallet.native_balance(CHAIN, address=address)
  except AuthError as exc:
    return exc.args


await credentials_check()

# %% [markdown]
# ## `Snapshots`

# %%
NATIVE_ASSET = 'native'
"""How the SDK's EVM impls label the chain's gas token in a `balances` dict."""
NATIVE_DECIMALS = 18


def is_native(token: TokenBalance) -> bool:
  """Whether a balance row is the chain's gas token.

  Moralis flags this with `native_token`. `token_address` is declared
  `NotRequired[str | None]`, so it cannot be used as the discriminator: the model permits
  it to be absent, null, or the zero-address placeholder, and which of the three the API
  actually sends for the native row is exactly the kind of thing a live response would
  settle. Unverified.
  """
  return bool(token.get('native_token'))


def token_amount(token: TokenBalance) -> Decimal:
  """Convert one balance row into display units.

  Moralis pre-scales the balance in `balance_formatted`, so that is preferred when
  present. The fallback tests `decimals is None`, not truthiness: a token declaring `0`
  decimals must keep its raw integer, and `decimals or 18` would report it as dust.
  """
  formatted = token.get('balance_formatted')
  if formatted is not None:
    return Decimal(formatted)
  decimals = token.get('decimals')
  if decimals is None:
    decimals = NATIVE_DECIMALS
  return Decimal(token['balance']) * (Decimal(10) ** -decimals)


def asset_id(token: TokenBalance) -> str | None:
  """The SDK asset key for a balance row, or `None` when it cannot be identified."""
  if is_native(token):
    return NATIVE_ASSET
  contract = token.get('token_address')
  return None if contract is None else Web3.to_checksum_address(contract)


# %%
async def token_balances() -> list[TokenBalance]:
  """Fetch every balance Moralis reports for the address on `CHAIN`.

  `exclude_spam` is deliberately left off. It is tempting -- most of this address's
  0-decimal holdings are airdrop spam -- but an accounting snapshot should report what
  the address holds and let the consumer filter, and turning it on would also hide the
  rows that make the decimals branch worth testing.
  """
  return list(
    await client.evm.wallet.token_balances_paged(address=address, chain=CHAIN)
  )


async def snapshot(assets: Collection[str] | None = None) -> SnapshotRecord:
  """Map Moralis balance rows onto a `SnapshotRecord`.

  Moralis enumerates holdings itself, so `assets` only narrows what is already there.

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
  for token in await token_balances():
    asset = asset_id(token)
    if asset is None or (wanted is not None and asset not in wanted):
      continue
    amount = token_amount(token)
    if amount != 0:
      balances[asset] += amount
  return SnapshotRecord(
    snapshot=Snapshot(subaccounts=[SubaccountSnapshot(balances=balances)]),
    provenance={'source': 'api', 'service': 'moralis', 'id': source_id('moralis')},
  )


# %% [markdown]
# The mapping is run below for real. It raises, because the account is out of quota -- that
# traceback is the honest state of this surface today, and it is left in the notebook
# rather than described in prose.

# %%
# not executed: the Moralis account behind MORALIS_API_KEY is out of quota; every Deep
# Index call answers 401 "usage is paused" (see the cell after setup)
await snapshot()

# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **Status: unverified.** No cell here read a real balance. `wallets/{address}/tokens`,
# `{address}/balance` and `wallets/{address}/history` all return `401` for this API key,
# so nothing below is "confirmed live" -- it is a reading of `typed_moralis` 0.2.1's
# declared models against the SDK contract, and it should be re-run before it is trusted.
#
# **What the declared contract supports.** `evm.wallet.token_balances` returns native and
# ERC-20 balances in one paged call, with `decimals`, `balance`, and a pre-scaled
# `balance_formatted`. On paper that is everything `SubaccountSnapshot.balances` needs, and
# `Snapshots.snapshot()` should be fully backed by one endpoint, the same shape as Alchemy.
# `positions` stays empty (an EVM address has no venue-side positions) and `Snapshot.time`
# stays at its default -- though unlike Alchemy, Moralis *does* return a `block_number` on
# the balances response, so a future `Snapshot` field for the block a read was pinned to
# would have something to hold here.
#
# **Two things a live response would have to settle**, both left explicit in the code
# above rather than guessed:
#
# 1. What `token_address` carries on the native row. The model says
#    `NotRequired[str | None]`, which permits absent, null, or a zero-address placeholder.
#    `is_native` therefore keys off `native_token` instead, and `asset_id` returns `None`
#    rather than crashing when a non-native row has no address.
# 2. Whether `balance_formatted` is present on every row. The model says `NotRequired`, so
#    `token_amount` keeps the raw-`balance` fallback; if it is in fact always present, the
#    fallback is dead code and the `decimals` handling never runs.
#
# ### `typed_moralis` 0.2.1 issues
#
# 1. **`TokenBalance.usd_price` is `NotRequired[str | float | None]` while `usd_value` is
#    `NotRequired[float | None]`.** Two fields from the same response, one modelled as
#    either a string or a float and the other only as a float. At least one of the two is
#    wrong, and a schema that admits `str | float` for a numeric field is not a contract a
#    caller can act on without re-sniffing the type at runtime. `TokenBalance.decimals`
#    (`int | None`) and `possible_spam` (`bool | None`) are modelled tightly, so the
#    looseness is not a house style -- it is specific to these fields. Suspected, not
#    confirmed: no live response was obtainable.
# 2. **`TokenBalance.balance` is the only required field on the row.** `token_address`,
#    `symbol`, `decimals` and `native_token` are all `NotRequired`, which forces every
#    consumer through `.get()` and a `None` branch for fields Moralis documents as always
#    present on an ERC-20 row.
#
# ### `tribulnation.ethereum.reporting.snapshots.moralis` -- two real bugs
#
# - `decimals = token.get('decimals') or NATIVE_DECIMALS` has the same 0-decimals defect as
#   the Alchemy impl: a token declaring `0` decimals gets divided by `10**18`. It is
#   partially masked there because `MoralisSnapshots.moralis_token_balances` passes
#   `exclude_spam=True`, and most 0-decimal tokens are spam -- masked, not fixed, and
#   masked by a filter that is itself a policy decision the snapshot should not be making
#   silently.
# - `address = token['token_address']` subscripts a `NotRequired[str | None]` field and
#   then passes it to `Web3.to_checksum_address(address)` on the non-native branch, which
#   raises on `None`. The guard above (`asset_id` returning `None`) is the missing part.
# - Separately, `MoralisSnapshots.moralis_token_balances` calls
#   `token_balances_paged(self.address, chain=..., exclude_spam=True)` positionally; the
#   0.2.1 signature is keyword-only (`address=`), so the impl does not run against the
#   installed client at all.
