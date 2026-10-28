# %%
import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import Any, AsyncIterator, Literal, TypedDict

from dotenv import load_dotenv
from typed_etherscan import Etherscan
from typed_etherscan.account.erc20_transfers import Erc20Transfer
from typed_etherscan.account.erc721_transfers import Erc721Transfer
from typed_etherscan.account.internal_transactions import InternalTransaction
from typed_etherscan.account.transactions import AccountTransaction

from tribulnation.sdk.reporting import EvmTx, Fee, HistoryRecord, source_id

load_dotenv()

CHAIN_ID = '42161'
"""Arbitrum One."""
PAGE_SIZE = 1000
NATIVE_ASSET = 'native'
WEI = Decimal(10) ** 18

client = Etherscan.new()
await client.__aenter__()
address = os.environ['EVM_ADDRESS']


# %% [markdown]
# > This notebook hand-maps `typed_etherscan`'s raw responses onto `tribulnation.sdk.reporting`
# > types directly -- it does not import or call `tribulnation.ethereum` at all, and it does
# > not reach for a node either: every field of `EvmTx`, including the receipt logs and the
# > `to`-is-an-EOA flag, comes out of Etherscan's own `proxy.*` endpoints. Everything below
# > is the **live, real** on-chain history of `EVM_ADDRESS`
# > (`0xE089aB95D28aCA5804a2F99c2cc259A88d3Be799`) on **Arbitrum One**.
# >
# > **Why Arbitrum One.** `sdk.test.toml` reuses the same `EVM_ADDRESS` across eight EVM
# > venues, so this had to be checked rather than assumed. Full-history row counts, pulled
# > live before writing:
# >
# > | chain | `txlist` | `txlistinternal` | `tokentx` | `tokennfttx` |
# > |---|---|---|---|---|
# > | Ethereum mainnet | 31 | 0 | 33 | 0 |
# > | Arbitrum One | 114 | 2 | 246 | 14 |
# > | Polygon | 6 | - | - | - |
# >
# > Ethereum mainnet has **no internal transactions and no NFT transfers at all**, so two
# > of the four feeds this mapping has to cover would have been unexercised there. Arbitrum
# > also carries the only failed transactions (4) and the only 0-decimal token transfers
# > (5) this address has anywhere, which are the two branches most likely to be got wrong.
# >
# > Reporting is read-only -- balance and history queries -- so every cell here runs live
# > and nothing spends gas.
# >
# > Out of scope: `History.history()` is the only method on this surface. Etherscan's
# > ERC-1155 feed (`token1155tx`) is checked in the population survey below and is empty
# > for this address on both chains, so it is reported as unexercised rather than mapped.

# %% [markdown]
# ## Resolving a time window to a block range

# %%
async def block_at(time: datetime, closest: Literal['before', 'after']) -> int:
  """Resolve a timestamp to the closest block number.

  `blocks.number_by_time` takes a `TimestampSeconds`, so it wants a `datetime` and
  serializes it to epoch seconds itself.
  """
  response = await client.blocks.number_by_time(
    CHAIN_ID, timestamp=time, closest=closest
  )
  return int(response['result'])


async def latest_block() -> int:
  """Fetch the chain head, for an open-ended window."""
  response = await client.proxy.eth_block_number(CHAIN_ID)
  return int(response.get('result') or '0x0', 16)


now = datetime.now(timezone.utc)
await block_at(now - timedelta(days=30), 'after'), await latest_block()


# %% [markdown]
# ### The four account feeds
#
# All four reach the client's own paging helpers. `contractaddress` is optional on
# `tokentx` and `tokennfttx`, and omitting it returns every token transfer of the address,
# which is what a history feed needs: it cannot know the contract set up front.
#

# %%
async def native_transactions(
  start_block: int, end_block: int
) -> list[AccountTransaction]:
  """Fetch every `txlist` row in the block range."""
  rows: list[AccountTransaction] = []
  async for page in client.account.transactions_paged(
    address=address,
    chainid=CHAIN_ID,
    startblock=start_block,
    endblock=end_block,
    offset=PAGE_SIZE,
    sort='asc',
  ):
    rows += page
  return rows


async def internal_transfers(
  start_block: int, end_block: int
) -> list[InternalTransaction]:
  """Fetch every `txlistinternal` row in the block range."""
  rows: list[InternalTransaction] = []
  async for page in client.account.internal_transactions_paged(
    address=address,
    chainid=CHAIN_ID,
    startblock=start_block,
    endblock=end_block,
    offset=PAGE_SIZE,
    sort='asc',
  ):
    rows += page
  return rows


async def token_transfers(start_block: int, end_block: int) -> list[Erc20Transfer]:
  """Fetch every `tokentx` row in the block range, across all contracts."""
  rows: list[Erc20Transfer] = []
  async for page in client.account.erc20_transfers_paged(
    address=address,
    chainid=CHAIN_ID,
    startblock=start_block,
    endblock=end_block,
    offset=PAGE_SIZE,
    sort='asc',
  ):
    rows += page
  return rows


async def nft_transfers(start_block: int, end_block: int) -> list[Erc721Transfer]:
  """Fetch every `tokennfttx` row in the block range, across all contracts."""
  rows: list[Erc721Transfer] = []
  async for page in client.account.erc721_transfers_paged(
    address=address,
    chainid=CHAIN_ID,
    startblock=start_block,
    endblock=end_block,
    offset=PAGE_SIZE,
    sort='asc',
  ):
    rows += page
  return rows



# %% [markdown]
# Each row comes back typed: `timeStamp` is a `datetime`, and `value`, `tokenDecimal`,
# `tokenID`, the gas fields and the block numbers are exact `int`s, so the grouping below
# reads them straight off the row.
#

# %%
class TxGroup(TypedDict):
  """Every feed row that shares one transaction hash, plus the block time."""

  time: datetime
  native: list[AccountTransaction]
  internal: list[InternalTransaction]
  erc20: list[Erc20Transfer]
  erc721: list[Erc721Transfer]


async def group_transactions(start_block: int, end_block: int) -> dict[str, TxGroup]:
  """Fetch all four account feeds and group every row by its transaction hash."""
  native, internal, erc20, erc721 = await asyncio.gather(
    native_transactions(start_block, end_block),
    internal_transfers(start_block, end_block),
    token_transfers(start_block, end_block),
    nft_transfers(start_block, end_block),
  )
  groups: dict[str, TxGroup] = {}

  def group(hash: str, time: datetime) -> TxGroup:
    if hash not in groups:
      groups[hash] = TxGroup(
        time=time, native=[], internal=[], erc20=[], erc721=[]
      )
    return groups[hash]

  for native_row in native:
    group(native_row['hash'], native_row['timeStamp'])['native'].append(native_row)
  for internal_row in internal:
    group(internal_row['hash'], internal_row['timeStamp'])['internal'].append(
      internal_row
    )
  for erc20_row in erc20:
    group(erc20_row['hash'], erc20_row['timeStamp'])['erc20'].append(erc20_row)
  for erc721_row in erc721:
    group(erc721_row['hash'], erc721_row['timeStamp'])['erc721'].append(erc721_row)
  return groups


everything = await group_transactions(0, await latest_block())
len(everything)


# %% [markdown]
# ### What the full population actually contains
#
# The mapping below has branches for a failed transaction, an internal (contract-initiated)
# native transfer, an ERC-721 transfer, a token declaring 0 decimals, and a transaction
# this address did not pay the fee for. Whether those branches are exercised is a fact
# about the *feed*, not about a hand-picked input list, so it is counted over the whole
# history rather than over a sample.

# %%
population = Counter(
  {
    'transactions': len(everything),
    'txlist rows': sum(len(group['native']) for group in everything.values()),
    'internal rows': sum(len(group['internal']) for group in everything.values()),
    'erc20 rows': sum(len(group['erc20']) for group in everything.values()),
    'erc721 rows': sum(len(group['erc721']) for group in everything.values()),
  }
)
failed = [
  hash
  for hash, group in everything.items()
  if any(row['isError'] == '1' for row in group['native'])
]
zero_decimal = [
  hash
  for hash, group in everything.items()
  if any(row['tokenDecimal'] == 0 for row in group['erc20'])
]
internal_only = [hash for hash, group in everything.items() if group['internal']]
with_nfts = [hash for hash, group in everything.items() if group['erc721']]
not_sender = [hash for hash, group in everything.items() if not group['native']]
(
  population,
  {
    'failed': len(failed),
    'zero-decimal token transfers': len(zero_decimal),
    'with internal transfers': len(internal_only),
    'with ERC-721 transfers': len(with_nfts),
    'fee paid by someone else': len(not_sender),
  },
)


# %%
# `token1155tx` is the one account feed with nothing behind it here, on either chain --
# recorded as a real empty rather than skipped, so it is not mistaken for coverage.
erc1155 = await client.account.erc1155_transfers(
  address=address, chainid=CHAIN_ID, offset=100, page=1
)
erc1155['status'], erc1155['message']

# %% [markdown]
# ## Transaction detail, from `proxy.*`

# %%
receipt_cache: dict[str, dict[str, Any]] = {}
tx_cache: dict[str, dict[str, Any]] = {}
eoa_cache: dict[str, bool] = {}


def hex_int(value: Any) -> int:
  """Parse a JSON-RPC hex quantity, treating a missing field as 0."""
  return 0 if value is None else int(value, 16)


def same_address(left: str | None, right: str | None) -> bool:
  """Compare two addresses case-insensitively, `None` never matching."""
  return left is not None and right is not None and left.lower() == right.lower()


async def get_receipt(hash: str) -> dict[str, Any]:
  """Fetch a transaction receipt, cached."""
  if hash not in receipt_cache:
    response = await client.proxy.eth_get_transaction_receipt(
      chainid=CHAIN_ID, txhash=hash
    )
    result = response.get('result')
    if result is None:
      raise ValueError(f'no receipt for {hash}')
    receipt_cache[hash] = result
  return receipt_cache[hash]


async def get_transaction(hash: str) -> dict[str, Any]:
  """Fetch a transaction by hash, cached."""
  if hash not in tx_cache:
    response = await client.proxy.eth_get_transaction_by_hash(
      chainid=CHAIN_ID, txhash=hash
    )
    result = response.get('result')
    if result is None:
      raise ValueError(f'no transaction for {hash}')
    tx_cache[hash] = result
  return tx_cache[hash]


async def is_eoa(contract: str) -> bool:
  """Check whether an address has no deployed bytecode, cached."""
  key = contract.lower()
  if key not in eoa_cache:
    response = await client.proxy.eth_get_code(chainid=CHAIN_ID, address=contract)
    eoa_cache[key] = (response.get('result') or '0x') == '0x'
  return eoa_cache[key]


# %% [markdown]
# ## Mapping onto `EvmTx`

# %%
def parse_fee(receipt: dict[str, Any]) -> Fee | None:
  """Map a receipt onto `Fee`, but only when this address is the one that paid it.

  `None` means "this address paid no fee", which is a different fact from a zero fee --
  so the guards below are `is not None`/`same_address`, never truthiness on the amount.
  A failed transaction still burns gas, and its fee is real.

  On Arbitrum the L1 data cost is already inside `gasUsed` (the receipt reports it
  separately as `gasUsedForL1`, but does not add it again), so `gasUsed *
  effectiveGasPrice` is the whole fee. OP-stack chains instead put it in a separate
  `l1Fee` field, which is added here when present -- absent on every Arbitrum receipt in
  this population, so that term is unexercised on this chain.
  """
  if not same_address(receipt.get('from'), address):
    return None
  gas_used = hex_int(receipt.get('gasUsed'))
  gas_price = hex_int(receipt.get('effectiveGasPrice'))
  l1_fee = hex_int(receipt.get('l1Fee'))
  return Fee(amount=Decimal(gas_used * gas_price + l1_fee) / WEI, asset=NATIVE_ASSET)


def parse_native_transfer(
  from_: str | None, to: str | None, wei: int, *, internal: bool
) -> EvmTx.NativeTransfer | None:
  """Map one native value movement onto `EvmTx.NativeTransfer`.

  Returns `None` when the movement carries no value, or when neither leg is this
  address -- an internal call between two third parties can show up in a transaction
  this address is otherwise part of.
  """
  if wei == 0:
    return None
  value = Decimal(wei) / WEI
  if same_address(to, address):
    change, counterparty = value, from_
  elif same_address(from_, address):
    change, counterparty = -value, to
  else:
    return None
  if counterparty is None:
    return None
  return EvmTx.NativeTransfer(
    change=change, counterparty=counterparty, internal=internal
  )


def parse_erc20_transfer(row: Erc20Transfer) -> EvmTx.ERC20Transfer | None:
  """Map one `tokentx` row onto `EvmTx.ERC20Transfer`.

  `tokenDecimal` is scaled with no fallback: 5 of this address's ERC-20 transfers are on
  tokens that declare `0` decimals, and a `decimals or 18` default would divide those by
  10**18.
  """
  value = Decimal(row['value']) * (Decimal(10) ** -row['tokenDecimal'])
  if same_address(row['to'], address):
    change, counterparty = value, row['from']
  elif same_address(row['from'], address):
    change, counterparty = -value, row['to']
  else:
    return None
  return EvmTx.ERC20Transfer(
    asset=row['contractAddress'], change=change, counterparty=counterparty
  )


def parse_erc721_transfer(row: Erc721Transfer) -> EvmTx.NftTransfer | None:
  """Map one `tokennfttx` row onto `EvmTx.NftTransfer`.

  `tokenID` is an `int` on the wire model and `EvmTx.NftTransfer.token_id` is a `str`,
  so it is stringified rather than coerced.
  """
  if same_address(row['to'], address):
    sign, counterparty = 1, row['from']
  elif same_address(row['from'], address):
    sign, counterparty = -1, row['to']
  else:
    return None
  return EvmTx.NftTransfer(
    contract_address=row['contractAddress'],
    token_id=str(row['tokenID']),
    change=Decimal(sign),
    counterparty=counterparty,
  )



# %%
async def parse_execution(hash: str) -> EvmTx.Execution:
  """Map a transaction and its receipt onto `EvmTx.Execution`."""
  transaction, receipt = await asyncio.gather(get_transaction(hash), get_receipt(hash))
  to = transaction.get('to')
  logs: list[Any] = receipt.get('logs') or []
  return EvmTx.Execution(
    to=to,
    input=transaction.get('input') or '0x',
    eoa=await is_eoa(to) if to is not None else False,
    canceled=hex_int(receipt.get('status')) == 0,
    logs=[
      EvmTx.Log(address=log['address'], data=log['data'], topics=list(log['topics']))
      for log in logs
    ],
  )


async def parse_tx(hash: str, group: TxGroup) -> EvmTx:
  """Map every feed row sharing one hash, plus its receipt, onto a single `EvmTx`.

  A reverted transaction moved nothing, so its transfers are dropped -- but its fee and
  its logs are kept, because both are real.
  """
  transaction, receipt = await asyncio.gather(get_transaction(hash), get_receipt(hash))
  transfers: list[EvmTx.Transfer] = []
  if hex_int(receipt.get('status')) != 0:
    outer = parse_native_transfer(
      transaction.get('from'),
      transaction.get('to'),
      hex_int(transaction.get('value')),
      internal=False,
    )
    if outer is not None:
      transfers.append(outer)
    for internal_row in group['internal']:
      transfer = parse_native_transfer(
        internal_row['from'],
        internal_row['to'],
        internal_row['value'],
        internal=True,
      )
      if transfer is not None:
        transfers.append(transfer)
    for erc20_row in group['erc20']:
      erc20_transfer = parse_erc20_transfer(erc20_row)
      if erc20_transfer is not None:
        transfers.append(erc20_transfer)
    for erc721_row in group['erc721']:
      erc721_transfer = parse_erc721_transfer(erc721_row)
      if erc721_transfer is not None:
        transfers.append(erc721_transfer)
  return EvmTx(
    id=hash,
    tx_id=hash,
    time=group['time'],
    fee=parse_fee(receipt),
    transfers=transfers,
    execution=await parse_execution(hash),
  )



# %% [markdown]
# ### The branch-triggering transactions
#
# One real transaction per branch, taken from the full-history survey above rather than
# chosen by hand -- so each of these is the population's own evidence that the branch
# fires.

# %%
async def parse_one(hash: str) -> EvmTx:
  """Map a single transaction out of the full-history grouping."""
  return await parse_tx(hash, everything[hash])


reverted = await parse_one(failed[0])
reverted.fee, reverted.execution.canceled, reverted.transfers

# %%
internal_tx = await parse_one(internal_only[0])
internal_tx.fee, internal_tx.transfers

# %%
nft_tx = await parse_one(with_nfts[0])
nft_tx.fee, nft_tx.transfers


# %%
zero_decimal_tx = await parse_one(zero_decimal[0])
zero_decimal_tx.fee, zero_decimal_tx.transfers


# %%
# A transaction this address did not send: `parse_fee` must return `None`, not a zero
# fee, and the ERC-20 leg must still be picked up.
inbound = await parse_one(not_sender[0])
inbound.fee, inbound.transfers


# %% [markdown]
# ## `History`

# %%
async def history(
  start: datetime | None = None, end: datetime | None = None
) -> AsyncIterator[HistoryRecord]:
  """Stream this address's on-chain history as `HistoryRecord`s.

  Args:
    start: Start of the window (inclusive). Genesis when omitted.
    end: End of the window (inclusive). The chain head when omitted.
  """
  id = source_id('etherscan')
  start_block = 0 if start is None else await block_at(start, 'after')
  end_block = await latest_block() if end is None else await block_at(end, 'before')
  groups = await group_transactions(start_block, end_block)
  semaphore = asyncio.Semaphore(4)

  async def parse_limited(hash: str, group: TxGroup) -> EvmTx:
    async with semaphore:
      return await parse_tx(hash, group)

  ordered = sorted(groups.items(), key=lambda item: item[1]['time'])
  parsed = await asyncio.gather(
    *(parse_limited(hash, group) for hash, group in ordered)
  )
  for tx in parsed:
    yield HistoryRecord(
      observations=[tx],
      provenance={'source': 'api', 'service': 'etherscan', 'id': id},
    )


end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
records = [record async for record in history(start, end)]
len(records)

# %%
# What the window actually produced, so an empty result could not pass as a clean run.
transfer_kinds = Counter(
  transfer.kind
  for record in records
  for observation in record.observations
  if isinstance(observation, EvmTx)
  for transfer in observation.transfers
)
fees_paid = sum(
  1
  for record in records
  for observation in record.observations
  if isinstance(observation, EvmTx) and observation.fee is not None
)
len(records), transfer_kinds, fees_paid

# %%
records[0]

# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **`History.history()` -- verified live, all four account feeds.** `EvmTx`'s fee,
# execution, logs, `eoa` flag and every transfer leg come out of Etherscan alone:
# `txlist`/`txlistinternal`/`tokentx`/`tokennfttx` give the rows and the block time,
# `proxy.eth_getTransactionReceipt` the fee inputs, revert status and logs,
# `proxy.eth_getTransactionByHash` `to`/`input`/`value`, `proxy.eth_getCode` the `eoa`
# flag. No node RPC is needed for any of it.
#
# | method | status | note |
# |---|---|---|
# | `history` (native, internal, fee, execution) | verified | 30-day window, live on Arbitrum One |
# | `history` (ERC-20, ERC-721 legs) | verified | 246 `tokentx` and 14 `tokennfttx` rows over the full history, no contract filter |
# | ERC-1155 | not supported | `token1155tx` empty for this address; `EvmTx.Transfer` has no member for it |
#
# **Branch coverage, against the whole feed rather than a sample.** The population survey
# counts, over this address's entire Arbitrum history: 256 transactions, 4 of them
# reverted, 2 internal native transfers, 14 ERC-721 transfers, 5 ERC-20 transfers on
# 0-decimal tokens, and 142 transactions whose fee this address did not pay. One of each is
# mapped above and the output shown. Two things are genuinely **unexercised** and are not
# claimed as covered: the `l1Fee` term in `parse_fee` (Arbitrum receipts do not carry the
# field -- it is an OP-stack shape), and ERC-1155 (`token1155tx` is empty for this address
# on both Arbitrum and Ethereum mainnet, confirmed live above; `EvmTx.Transfer` has no
# ERC-1155 member either, so there would be nowhere to put one).
#
# **What does not map.** `EvmTx` has no member for an ERC-1155 transfer, so a
# semi-fungible balance change would have to be forced into `NftTransfer` (losing the
# amount) or `ERC20Transfer` (losing the token id). Worth raising against the model rather
# than working around in an impl.
#
# ---
#
# ### `typed_etherscan` issues still open here
#
# 1. **`proxy.*` results are `dict[str, Any] | None`.** Receipts, transactions and logs
#    have fixed, well-known shapes; typing them would have caught the two mistakes this
#    notebook made while being written.
# 2. **`sort` is typed `str`** on every paged account endpoint, where only `asc`/`desc`
#    are valid.
#
# Fixed since the first pass and re-run clean above: `contractaddress` is optional on
# `erc20_transfers_paged`/`erc721_transfers_paged`, `erc721_transfers` has a row model, and
# every field of the six account feeds carries a real type (`timeStamp` a `datetime`,
# `value`/`tokenDecimal`/`tokenID` and the gas and block fields exact `int`s).
#
