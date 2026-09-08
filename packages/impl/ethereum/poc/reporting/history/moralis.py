# %%
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import Any, AsyncIterator

from dotenv import load_dotenv
from typed_moralis import AuthError, Moralis
from typed_moralis.evm.wallet.history import (
  Erc20Transfer,
  NativeTransfer,
  WalletHistoryTransaction,
)

from tribulnation.sdk.reporting import (
  CryptoTransaction,
  CryptoTransfer,
  EvmTx,
  Fee,
  HistoryRecord,
  source_id,
)

load_dotenv()

CHAIN = 'arbitrum'
NATIVE_ASSET = 'native'
NATIVE_DECIMALS = 18

client = Moralis.new()
await client.__aenter__()
address = os.environ['EVM_ADDRESS']


# %% [markdown]
# > **This notebook did not get live data. The Moralis account behind `MORALIS_API_KEY` is
# > out of quota**, and every Deep Index endpoint answers `401` with
# > `"Your Moralis Free usage is paused. Upgrade to a paid plan to resume usage."` The next
# > cell shows that response unedited, and the same 401 comes back from a raw `httpx` GET
# > to `https://deep-index.moralis.io/api/v2.2/wallets/<address>/history` -- it is an
# > account-billing state, not a bad key and not a client bug.
# >
# > So the mapping below is derived from `typed_moralis` 0.2.1's **declared response
# > models**, not from observed responses, and it is not verified. The next cell shows the
# > 401 as it comes off the wire; the mapping cell at the end is left unexecuted until
# > the account has quota.
# >
# > Network: **Arbitrum One**, matching the other four notebooks in this directory --
# > `EVM_ADDRESS` has 256 distinct transactions there against 64 on Ethereum mainnet, and
# > Arbitrum carries the only internal transfers, NFT transfers and reverted transactions
# > this address has anywhere.
# >
# > The interesting result here is structural and does not need live data: **Moralis's
# > wallet history cannot back `EvmTx` on its own.** `WalletHistoryTransaction` carries no
# > `input`, no `logs`, and no `nft_transfers`; `blockchain.transaction` supplies the first
# > two at one extra call per transaction, but *nothing* in `typed_moralis` answers "is
# > this address a contract", which `EvmTx.Execution.eoa` requires. What Moralis does back
# > cleanly, in one paged call, is `CryptoTransaction`. Both mappings are written below,
# > the second with the gap in its own signature.

# %%
async def credentials_check() -> object:
  """Call the history endpoint and report what comes back."""
  try:
    return await client.evm.wallet.history(address=address, chain=CHAIN, limit=1)
  except AuthError as exc:
    return exc.args


await credentials_check()


# %% [markdown]
# ## Reading the feed

# %%
async def wallet_history(
  start: datetime | None = None, end: datetime | None = None
) -> list[WalletHistoryTransaction]:
  """Fetch decoded wallet activity for the address, oldest first.

  Moralis takes the window as `from_date`/`to_date` strings and documents that it
  accepts "seconds or a date string"; ISO-8601 is passed here. `history_paged` is
  awaitable and flattens every page.
  """
  return list(
    await client.evm.wallet.history_paged(
      address=address,
      chain=CHAIN,
      from_date=None if start is None else start.isoformat(),
      to_date=None if end is None else end.isoformat(),
      order='ASC',
    )
  )


# %%
def same_address(left: str | None, right: str | None) -> bool:
  """Compare two addresses case-insensitively, `None` never matching."""
  return left is not None and right is not None and left.lower() == right.lower()


def scaled(value: str | float | None, formatted: str | None, decimals: int) -> Decimal:
  """Scale a Moralis amount, preferring the pre-formatted value when present."""
  if formatted is not None:
    return Decimal(formatted)
  return Decimal(str(value or 0)) * (Decimal(10) ** -decimals)


def native_value(transfer: NativeTransfer) -> Decimal:
  """A native transfer's value in display units."""
  return scaled(transfer.get('value'), transfer.get('value_formatted'), NATIVE_DECIMALS)


def token_value(transfer: Erc20Transfer) -> Decimal:
  """An ERC-20 transfer's value in display units.

  `token_decimals` is declared `str | int | None`. `None` genuinely means unknown, and
  `0` is a real, common value on airdrop tokens, so the two are separated: only the
  first falls back. A `decimals or 18` fallback would divide a 0-decimal amount by
  10**18.
  """
  decimals = transfer.get('token_decimals')
  return scaled(
    transfer.get('value'),
    transfer.get('value_formatted'),
    NATIVE_DECIMALS if decimals is None else int(decimals),
  )


def signed(
  amount: Decimal, from_: str | None, to: str | None
) -> tuple[Decimal, str] | None:
  """Sign an amount from this address's perspective, with the counterparty.

  `None` when neither leg is this address -- Moralis returns whole transactions, so a
  row can contain transfers between two third parties.
  """
  if same_address(to, address):
    return amount, from_ or ''
  if same_address(from_, address):
    return -amount, to or ''
  return None


# %% [markdown]
# ## `CryptoTransaction` -- what Moralis backs on its own
#
# One paged call covers it: `CryptoTransaction` needs a hash, a fee and a list of
# `{asset, change, counterparty}`, and every one of those is on the history row.

# %%
def parse_fee(row: WalletHistoryTransaction) -> Fee | None:
  """Map the row's fee, but only when this address is the sender that paid it.

  The guard is `is not None`, not truthiness: a zero fee is a real, reportable value,
  and `if fee:` would silently drop it.
  """
  fee = row.get('transaction_fee')
  if fee is None or not same_address(row.get('from_address'), address):
    return None
  return Fee(amount=Decimal(fee), asset=NATIVE_ASSET)


def crypto_transfers(row: WalletHistoryTransaction) -> list[CryptoTransfer]:
  """Map the row's native and ERC-20 legs onto `CryptoTransfer`."""
  transfers: list[CryptoTransfer] = []
  for native in row.get('native_transfers') or []:
    change = signed(
      native_value(native), native.get('from_address'), native.get('to_address')
    )
    if change is not None:
      amount, counterparty = change
      transfers.append(
        CryptoTransfer(asset=NATIVE_ASSET, change=amount, counterparty=counterparty)
      )
  for token in row.get('erc20_transfers') or []:
    contract = token.get('address')
    if contract is None:
      continue
    change = signed(
      token_value(token), token.get('from_address'), token.get('to_address')
    )
    if change is not None:
      amount, counterparty = change
      transfers.append(
        CryptoTransfer(asset=contract, change=amount, counterparty=counterparty)
      )
  return transfers


def crypto_transaction(row: WalletHistoryTransaction) -> CryptoTransaction:
  """Map one wallet-history row onto `CryptoTransaction`.

  A reverted transaction moved nothing, so its transfers are dropped while its fee is
  kept. `receipt_status` is declared `str | int | None`, hence the string comparison
  against a normalised value rather than `== 0`.
  """
  reverted = str(row.get('receipt_status')) == '0'
  return CryptoTransaction(
    id=row['hash'],
    tx_id=row['hash'],
    time=row['block_timestamp'],
    fee=parse_fee(row),
    transfers=[] if reverted else crypto_transfers(row),
  )


async def history(
  start: datetime | None = None, end: datetime | None = None
) -> AsyncIterator[HistoryRecord]:
  """Stream this address's on-chain history as `HistoryRecord`s.

  Args:
    start: Start of the window (inclusive). Everything Moralis has when omitted.
    end: End of the window (inclusive). Now when omitted.
  """
  id = source_id('moralis')
  for row in await wallet_history(start, end):
    yield HistoryRecord(
      observations=[crypto_transaction(row)],
      provenance={'source': 'api', 'service': 'moralis', 'id': id},
    )


# %% [markdown]
# ## `EvmTx` -- what Moralis cannot back on its own
#
# `EvmTx.Execution` needs `input`, `logs`, `canceled` and `eoa`.
# `WalletHistoryTransaction` has none of the four; `blockchain.transaction` has the first
# three, at one extra call per transaction. `eoa` -- whether the `to` address holds
# bytecode -- has no answer anywhere in `typed_moralis`: there is no `eth_getCode`
# equivalent and no account-type field on any response. So it is a required parameter
# below rather than a fabricated `False`. The shipped `MoralisHistory` fills it from a
# `web3` node, which is the same admission made structurally.
#
# `nft_transfers` is a second, smaller gap: the endpoint's own docstring says the response
# includes NFT transfers, but `WalletHistoryTransaction` declares no such field, so
# `EvmTx.NftTransfer` has nothing to read here.

# %%
async def transaction_detail(hash: str) -> dict[str, Any]:
  """Fetch the execution detail the wallet-history row does not carry."""
  return dict(
    await client.evm.blockchain.transaction(
      transaction_hash=hash, chain=CHAIN, include='internal_transactions'
    )
  )


async def evm_tx(row: WalletHistoryTransaction, *, to_is_eoa: bool) -> EvmTx:
  """Map one wallet-history row onto `EvmTx`, given the one fact Moralis cannot supply.

  Args:
    row: The wallet-history row.
    to_is_eoa: Whether the `to` address is an externally owned account. Not derivable
      from any `typed_moralis` endpoint -- it has to come from a node or another
      provider, which is what makes this mapping impure.
  """
  detail = await transaction_detail(row['hash'])
  logs: list[Any] = detail.get('logs') or []
  reverted = str(detail.get('receipt_status') or row.get('receipt_status')) == '0'
  transfers: list[EvmTx.Transfer] = []
  if not reverted:
    for transfer in crypto_transfers(row):
      if transfer.asset == NATIVE_ASSET:
        transfers.append(
          EvmTx.NativeTransfer(
            change=transfer.change,
            counterparty=transfer.counterparty or '',
            internal=False,
          )
        )
      else:
        transfers.append(
          EvmTx.ERC20Transfer(
            asset=transfer.asset,
            change=transfer.change,
            counterparty=transfer.counterparty or '',
          )
        )
  return EvmTx(
    id=row['hash'],
    tx_id=row['hash'],
    time=row['block_timestamp'],
    fee=parse_fee(row),
    transfers=transfers,
    execution=EvmTx.Execution(
      to=detail.get('to_address'),
      input=detail.get('input') or '0x',
      eoa=to_is_eoa,
      canceled=reverted,
      logs=[
        EvmTx.Log(address=log['address'], data=log['data'], topics=list(log['topics']))
        for log in logs
      ],
    ),
  )


# %% [markdown]
# Run for real. It raises, because the account is out of quota -- left in the notebook
# rather than described.

# %%
# not executed: the Moralis account behind MORALIS_API_KEY is out of quota; every Deep
# Index call answers 401 "usage is paused" (see the cell after setup)
end = datetime.now(timezone.utc)
start = end - timedelta(days=30)
[record async for record in history(start, end)]

# %% [markdown]
# ## Coverage assessment

# %% [markdown]
# **Status: unverified.** Nothing here read a real transaction. `wallets/{address}/history`
# returns `401` for this API key, so the mapping is a reading of `typed_moralis` 0.2.1's
# declared models against the SDK contract, not an observed result. It should be re-run
# against a funded account before it is trusted.
#
# **`History.history()` -> `CryptoTransaction`: backed, one call.** `evm.wallet.history`
# returns whole transactions with `hash`, `block_timestamp` (already an aware `datetime`
# via `TimestampIso`), `transaction_fee`, `receipt_status`, and decoded `native_transfers`
# / `erc20_transfers` carrying pre-scaled `value_formatted`. That is every field
# `CryptoTransaction` and `CryptoTransfer` have. No second endpoint, no node.
#
# **`History.history()` -> `EvmTx`: not backed, and the missing piece is not a rounding
# error.** Three gaps, in order of severity:
#
# 1. **`Execution.eoa` is unobtainable.** No `typed_moralis` endpoint returns contract
#    bytecode or an account-type flag. `eoa` is a required `bool` on `EvmTx.Execution`, so
#    a Moralis-only mapping would have to invent it. This notebook makes it a parameter
#    instead. `tribulnation.ethereum.reporting.history.moralis.MoralisHistory` inherits
#    `HistoryMixin`, which holds a `web3` `NodeRpc` and calls `eth_getCode` -- so the
#    shipped "Moralis history source" is already a Moralis-plus-node source, and its
#    `impl.toml` entry arguably overstates what the provider does.
# 2. **`input` and `logs` need a second call per transaction.**
#    `evm.blockchain.transaction` has both, so the data exists, but a 250-transaction
#    history becomes 250 extra requests. Etherscan has the same shape
#    (`proxy.eth_getTransactionReceipt`), so this is a cost, not a blocker.
# 3. **NFT transfers are missing from the model entirely** -- see the client issues below.
#
# ### `typed_moralis` 0.2.1 issues
#
# 1. **`evm.wallet.history`'s `WalletHistoryTransaction` has no `nft_transfers` field**,
#    while the endpoint's own generated docstring says the response includes "native
#    transfers, ERC20 transfers, NFT transfers, fees, logs, labels". Moralis's wallet
#    history does return `nft_transfers`. The model also omits `logs`,
#    `internal_transactions`, `method_label`, `summary` and `possible_spam`, all of which
#    the same docstring or the upstream docs describe. Suspected, not confirmed: no live
#    response was obtainable.
# 2. **`NativeTransfer` has no `internal_transaction` flag.** Moralis marks
#    contract-initiated native movements with one, and `EvmTx.NativeTransfer.internal`
#    needs exactly that bit -- the mapping above has to hardcode `internal=False`.
#    `tribulnation.ethereum.reporting.history.moralis` already reads
#    `transfer.get('internal_transaction')`, so the field was there when that code was
#    written; it is not in the 0.2.1 model.
# 3. **Union-typed numeric and boolean fields throughout.**
#    `WalletHistoryTransaction.receipt_status` is `str | int | None`, `.value` is
#    `str | float | None`, `.block_number` is `str | int`; `Erc20Transfer.value` is
#    `str | float`, `.token_decimals` is `str | int | None`, `.possible_spam` and
#    `.verified_contract` are `bool | str | None`. A boolean that may arrive as a string is
#    not a contract a caller can branch on -- and these sit next to tightly typed fields in
#    the same model, so the looseness looks like inference from thin samples rather than a
#    deliberate choice.
# 4. **`TransactionResponse.logs` and `.internal_transactions` are
#    `list[dict[str, Any]]`** -- no item model, on the endpoint whose whole purpose here is
#    supplying structured logs.
#
# ### `tribulnation.ethereum.reporting.history.moralis` -- broken against this client
#
# - It imports `NftTransfer` and `TokenTransfer` from
#   `typed_moralis.evm.wallet.history`. Neither name exists in 0.2.1 (`TokenTransfer` was
#   renamed `Erc20Transfer`; `NftTransfer` is gone with the field).
# - `parse_nft_transfers` reads `tx.get('nft_transfers', [])`, a key the model no longer
#   declares.
# - `parse_moralis_native_transfer` reads `transfer.get('internal_transaction')`, likewise
#   undeclared.
# - `wallet_history` calls `history_paged(self.address, chain=..., from_date=...,
#   include_internal_transactions=True)`. In 0.2.1 the method is keyword-only and has no
#   `include_internal_transactions` parameter at all.
# - `parse_moralis_fee` guards with `if (fee := tx.get('transaction_fee')) and ...`. It
#   happens to be safe today (Moralis sends the fee as a string, and `'0'` is truthy) but
#   it is the same truthiness-on-a-number shape that is a real bug elsewhere in this
#   package, and `is not None` costs nothing.
# - `parse_moralis_tx` raises `ValueError` on any fee mismatch between the node-derived fee
#   and Moralis's, including the case where one is `None` and the other is not -- which is
#   exactly what happens on a transaction this address did not send, since
#   `HistoryMixin.parse_fee` and `parse_moralis_fee` disagree about whether to look at the
#   receipt's `from` or the history row's `from_address`. Untested here, but worth a look.
