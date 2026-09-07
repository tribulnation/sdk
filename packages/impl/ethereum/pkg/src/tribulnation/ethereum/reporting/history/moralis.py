"""Moralis-backed EVM history: the wallet-history feed gives whole transactions with
their decoded native and ERC-20 legs, the node gives the receipt, input and bytecode
check. NFT legs are not read: `WalletHistoryTransaction` declares no `nft_transfers`
field.
"""

from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  TypeVar,
)
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
import asyncio

from typed_moralis import Moralis
from typed_moralis.schemas import WalletEvmChain
from typed_moralis.evm.wallet.history import (
  WalletHistoryTransaction,
  NativeTransfer,
  Erc20Transfer as TokenTransfer,
)

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import History, HistoryRecord, EvmTx, Fee, source_id
from tribulnation.ethereum.core import Network, moralis as moralis_core, same_address
from tribulnation.ethereum.reporting.history.mixin import HistoryMixin

T = TypeVar('T')

NATIVE_DECIMALS = 18


def scaled(value: str | float | None, formatted: str | None, decimals: int) -> Decimal:
  """Scale a Moralis amount, preferring the pre-formatted value when present."""
  if formatted is not None:
    return Decimal(formatted)
  return Decimal(str(value or 0)) * (Decimal(10) ** -decimals)


def native_value(transfer: NativeTransfer) -> Decimal:
  """Return a native transfer value in display units."""
  return scaled(transfer.get('value'), transfer.get('value_formatted'), NATIVE_DECIMALS)


def token_value(transfer: TokenTransfer) -> Decimal:
  """Return an ERC-20 transfer value in display units.

  `token_decimals` is `None` when unknown, and `0` is a real value on airdrop tokens, so
  only the first falls back to the native scale.
  """
  decimals = transfer.get('token_decimals')
  return scaled(
    transfer.get('value'),
    transfer.get('value_formatted'),
    NATIVE_DECIMALS if decimals is None else int(decimals),
  )


@dataclass(frozen=True, kw_only=True)
class MoralisHistory(HistoryMixin, History):
  """Moralis-backed EVM history source."""

  address: str
  chain: WalletEvmChain
  moralis: Moralis = field(default_factory=Moralis.new)
  batch_size: int = 4

  @classmethod
  def new(
    cls,
    address: str,
    *,
    network: Network,
    rpc_url: str | None = None,
    api_key: str | None = None,
  ):
    from tribulnation.ethereum.core import rpc, MORALIS_CHAINS

    node, rpc_url = rpc.new(network, rpc_url, preferred='alchemy')
    return cls(
      address=address,
      chain=MORALIS_CHAINS[network],
      node=node,
      rpc_url=rpc_url,
      moralis=Moralis.new(api_key),
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.moralis

  @SDK.method
  @moralis_core.wrap_exceptions
  async def call_moralis(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Moralis under the SDK exception wrapper."""
    return await fn()

  async def wallet_history(
    self, start: datetime | None = None, end: datetime | None = None
  ):
    """Yield the wallet-history feed one page at a time, oldest first."""
    paging = self.moralis.evm.wallet.history_paged(
      address=self.address,
      chain=self.chain,
      from_date=None if start is None else start.isoformat(),
      to_date=None if end is None else end.isoformat(),
      order='ASC',
    )
    async for chunk in paging.via(self.call_moralis):
      yield chunk

  def signed(
    self, amount: Decimal, from_: str | None, to: str | None
  ) -> tuple[Decimal, str] | None:
    """Sign an amount from this address's perspective, with the counterparty.

    `None` when neither leg is this address: Moralis returns whole transactions, so a
    row can carry transfers between two third parties.
    """
    if to is not None and same_address(to, self.address):
      return (amount, from_) if from_ is not None else None
    if from_ is not None and same_address(from_, self.address):
      return (-amount, to) if to is not None else None
    return None

  def parse_moralis_fee(self, tx: WalletHistoryTransaction) -> Fee | None:
    """Parse the row's fee, when this address is the sender that paid it."""
    fee, from_ = tx.get('transaction_fee'), tx.get('from_address')
    if fee is None or from_ is None or not same_address(from_, self.address):
      return None
    return Fee(amount=Decimal(fee), asset='native')

  def parse_moralis_native_transfers(
    self, tx: WalletHistoryTransaction
  ) -> list[EvmTx.NativeTransfer]:
    """Parse the row's decoded native legs."""
    transfers: list[EvmTx.NativeTransfer] = []
    for transfer in tx.get('native_transfers') or []:
      change = self.signed(
        native_value(transfer), transfer.get('from_address'), transfer.get('to_address')
      )
      if change is not None:
        amount, counterparty = change
        transfers.append(
          EvmTx.NativeTransfer(
            change=amount,
            counterparty=counterparty,
            internal=transfer.get('internal_transaction') is not None,
          )
        )
    return transfers

  def parse_token_transfers(
    self, tx: WalletHistoryTransaction
  ) -> list[EvmTx.ERC20Transfer]:
    """Parse the row's decoded ERC-20 legs."""
    transfers: list[EvmTx.ERC20Transfer] = []
    for transfer in tx.get('erc20_transfers') or []:
      contract = transfer.get('address')
      if contract is None:
        continue
      change = self.signed(
        token_value(transfer), transfer.get('from_address'), transfer.get('to_address')
      )
      if change is not None:
        amount, counterparty = change
        transfers.append(
          EvmTx.ERC20Transfer(asset=contract, change=amount, counterparty=counterparty)
        )
    return transfers

  async def parse_moralis_tx(self, wallet_tx: WalletHistoryTransaction) -> EvmTx:
    """Map one wallet-history row, plus the node's receipt, onto an `EvmTx`."""
    hash = wallet_tx['hash']
    tx, receipt = await self.get_tx_data(hash)
    transfers: list[EvmTx.Transfer] = []
    if receipt['status'] != 0:
      transfers = [
        *self.parse_moralis_native_transfers(wallet_tx),
        *self.parse_token_transfers(wallet_tx),
      ]
    fee_node = self.parse_fee(tx, receipt)
    fee_moralis = self.parse_moralis_fee(wallet_tx)
    if (fee_node is None) != (fee_moralis is None):
      raise ValueError(f'Fee mismatch: {fee_node} != {fee_moralis}')
    if fee_node and fee_moralis and fee_node.amount != fee_moralis.amount:
      raise ValueError(f'Fee mismatch: {fee_node.amount} != {fee_moralis.amount}')
    return EvmTx(
      id=hash,
      tx_id=hash,
      time=wallet_tx['block_timestamp'],
      fee=fee_node,
      transfers=transfers,
      execution=await self.parse_execution(tx, receipt),
    )

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    id = source_id('moralis')
    semaphore = asyncio.Semaphore(self.batch_size)

    async def parse_limited(wallet_tx: WalletHistoryTransaction):
      async with semaphore:
        return await self.parse_moralis_tx(wallet_tx)

    async for chunk in self.wallet_history(start=start, end=end):
      for tx in chunk:
        yield HistoryRecord(
          observations=[await parse_limited(tx)],
          provenance={'source': 'api', 'service': 'moralis', 'id': id},
        )
