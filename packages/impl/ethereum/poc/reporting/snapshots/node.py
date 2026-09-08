# %%
import asyncio
import os
from decimal import Decimal
from typing_extensions import Collection

from dotenv import load_dotenv
from web3 import Web3
from web3.exceptions import BadFunctionCallOutput, ContractLogicError
from typed_ethereum import NodeRpc, PUBLIC_NODE_URLS

from tribulnation.sdk.reporting import (
  Balances,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
  source_id,
)

load_dotenv()

NETWORK = 'arbitrum'
RPC_URL = PUBLIC_NODE_URLS[NETWORK]
client = NodeRpc.at(RPC_URL)
await client.__aenter__()
address = os.environ['EVM_ADDRESS']
RPC_URL

# %% [markdown]
# > This notebook hand-maps `typed_ethereum`'s `NodeRpc` onto `tribulnation.sdk.reporting`
# > types directly -- it does not import or call `tribulnation.ethereum` at all. Every
# > balance below is the **live, real** holdings of `EVM_ADDRESS`
# > (`0xE089aB95D28aCA5804a2F99c2cc259A88d3Be799`) on **Arbitrum One**, read from the
# > public RPC node at `https://arbitrum-one-rpc.publicnode.com` -- no API key involved,
# > which is the point of this source.
# >
# > **Why Arbitrum One.** Same reason as the Alchemy notebook next to this one: the shared
# > `EVM_ADDRESS` is active on several chains, and Arbitrum is where it holds both ordinary
# > 6- and 18-decimal tokens *and* tokens declaring **0 decimals**, so a decimals bug shows
# > up here instead of hiding.
# >
# > **The structural limit of this source.** A node answers `balanceOf(address)` on a
# > contract you name; it cannot enumerate what an address holds. So unlike Alchemy or
# > Moralis, `snapshot()` here reports the native balance plus exactly the ERC-20 contracts
# > passed in `assets`, and nothing else. That is not a gap in the mapping -- it is what
# > the SDK's `Snapshots.snapshot(assets=...)` parameter exists for.

# %% [markdown]
# ## `Snapshots`

# %%
NATIVE_ASSET = 'native'
"""How the SDK's EVM impls label the chain's gas token in a `balances` dict."""

# Real Arbitrum One contracts this address holds, chosen to span the decimal cases:
# 6-decimal USDC, 18-decimal WETH and DAI, and a 0-decimal airdrop token. The last entry
# is deliberately *not* an ERC-20 -- it is a real deployed contract this address has
# interacted with (24 KB of bytecode, and the ERC-721 minter behind one of the NFT
# transfers in the Etherscan history notebook) that has no `balanceOf(address)` -- to
# exercise the failure branch below.
USDC = '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'
WETH = '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1'
DAI = '0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1'
ZERO_DECIMAL = '0x42c35b14e6f163eA0a625C919Dd95F5a3a594C19'
NOT_A_TOKEN = '0x46A15B0b27311cedf172AB29E4f4766fbE7F4364'

ASSETS = [USDC, WETH, DAI, ZERO_DECIMAL, NOT_A_TOKEN]


# %%
async def native_balance() -> Decimal:
  """Fetch the chain's gas-token balance, already scaled to ETH by `typed_ethereum`."""
  return await client.eth_balance(address)


await native_balance()


# %%
async def token_metadata(contract: str) -> tuple[str, int]:
  """Fetch an ERC-20's symbol and decimals, straight off the contract."""
  token = client.token(contract)
  symbol, decimals = await asyncio.gather(token.symbol(), token.decimals())
  return symbol, decimals


# `typed_ethereum.ERC20.balance()` divides `balanceOf` by `10 ** decimals()`, both read
# from the contract itself -- so the 0-decimal case is right by construction here, with
# no fallback to get wrong. Confirmed against the real contracts:
[(contract, await token_metadata(contract)) for contract in (USDC, WETH, ZERO_DECIMAL)]


# %%
async def token_balance(contract: str) -> Decimal | None:
  """Fetch one ERC-20 balance, or `None` when the address is not a working ERC-20.

  A plain `eth_call` to `balanceOf` on something that is not a token does not return
  zero -- it reverts (`ContractLogicError`) or returns no data to decode
  (`BadFunctionCallOutput`). Both mean "unknown", not "nothing", so neither is folded
  into a `0` balance.
  """
  try:
    return await client.token(contract).balance(address)
  except (ContractLogicError, BadFunctionCallOutput):
    return None


[(contract, await token_balance(contract)) for contract in ASSETS]


# %%
async def snapshot(assets: Collection[str] | None = None) -> SnapshotRecord:
  """Map node reads onto a `SnapshotRecord`.

  A node cannot enumerate holdings, so this reports the native balance plus exactly the
  ERC-20 contracts named in `assets`. A contract that does not answer `balanceOf` is
  skipped rather than recorded as zero; a real zero balance is recorded, because a
  confirmed zero is information the node did give us.

  Args:
    assets: Contract addresses (any casing) to read. Native only when omitted.
  """
  contracts = [
    Web3.to_checksum_address(asset) for asset in (assets or []) if asset != NATIVE_ASSET
  ]
  native_task = asyncio.create_task(native_balance())
  token_balances = await asyncio.gather(
    *(token_balance(contract) for contract in contracts)
  )
  balances = Balances({NATIVE_ASSET: await native_task})
  for contract, balance in zip(contracts, token_balances):
    if balance is not None:
      balances[contract] = balance
  return SnapshotRecord(
    snapshot=Snapshot(subaccounts=[SubaccountSnapshot(balances=balances)]),
    provenance={'source': 'api', 'service': 'node_rpc', 'id': source_id('node_rpc')},
  )


await snapshot(ASSETS)

# %%
# With no asset list there is nothing to enumerate, so the snapshot is native-only.
await snapshot()

# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **`Snapshots.snapshot()` -- backed, within the source's structural limit.** `NodeRpc`
# gives `eth_getBalance` for the gas token and `balanceOf`/`decimals`/`symbol` on any
# ERC-20, which is everything `SubaccountSnapshot.balances` needs. It ran live against the
# public Arbitrum node and returned real balances for all four token contracts plus the
# native one. `positions` stays empty (an EVM address has no venue-side positions) and
# `Snapshot.time` stays at its default; the node could pin the read to a block number, but
# `Snapshot` has no field for one.
#
# **Not backed: discovery.** A node has no "what does this address hold" query, so
# `snapshot()` with no `assets` is native-only, as the last cell shows. That is the whole
# reason `SnapshotSourcesConfig` documents `node` as the source that "cannot [combine asset
# discovery and balance retrieval], and reports only the native asset unless assets are
# given" -- confirmed, not just asserted.
#
# **Decimals are right by construction here.** `typed_ethereum.ERC20.balance()` reads
# `decimals()` off the contract and divides by `10 ** decimals`, with no default to fall
# back to -- so the 0-decimal token that the Alchemy mapping gets wrong
# (`decimals or 18`) comes out as the integer `1` here. The cell above confirms it live
# against `0x42c3...4C19`, whose contract really does report `decimals() == 0`.
#
# **A judgement call the impl makes differently.** `tribulnation.ethereum.reporting
# .snapshots.node.NodeSnapshots` defaults `ignore_zero_value=True` and drops any balance
# that is not `> 0`. This notebook keeps a confirmed zero: the node was asked and
# answered, and "zero" is a different fact from "not looked up". Both behaviours are
# defensible, but they are not the same record, and the impl's is the lossier one.
#
# **Two smaller notes on the impl's node mapping.** It wraps an already-`Decimal` return
# in `Decimal(...)` twice (`Decimal(await self.node.eth_balance(...))`,
# `Decimal(await self.node.token(contract).balance(...))`) -- harmless, but it reads as
# though the client returned an int. And it catches `ContractLogicError` /
# `BadFunctionCallOutput` and, when `ignore_bad_contracts` is off, re-raises them as
# `ApiError`; that is the right pair of exceptions, confirmed live here -- a deployed
# contract with no `balanceOf(address)` raises `ContractLogicError('execution reverted',
# '0x')`.
