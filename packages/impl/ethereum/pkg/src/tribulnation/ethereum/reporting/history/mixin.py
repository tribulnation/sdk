"""What every EVM history source shares: the node reads (transaction, receipt, bytecode)
and the parsing of fee, execution and native value movements out of them.
"""

from typing_extensions import Any, AsyncContextManager, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
import asyncio

from hexbytes import HexBytes
from web3 import Web3
from web3.types import TxReceipt, TxData
from typed_ethereum import NodeRpc

from tribulnation.sdk.core import SDK, managed_tasks
from tribulnation.sdk.reporting import EvmTx, Fee
from tribulnation.ethereum.core import rpc, wei2eth, same_address


def wei_field(value: Any) -> Decimal:
  """Return a wei-valued receipt field as a decimal integer, `0` when absent."""
  if value is None:
    return Decimal(0)
  if isinstance(value, str) and value.startswith('0x'):
    return Decimal(int(value, 16))
  return Decimal(value)


def tx_fee(receipt: TxReceipt) -> Decimal:
  """Return the full transaction fee in native units.

  `l1Fee` (OP-stack) and `operatorFee` are chain extensions web3's `TxReceipt` doesn't
  declare, so they are read off the plain mapping.
  """
  extra: dict[str, Any] = dict(receipt)
  used = wei_field(receipt.get('gasUsed'))
  price = wei_field(receipt.get('effectiveGasPrice'))
  l1_fee = wei_field(extra.get('l1Fee'))
  operator_fee = wei_field(extra.get('operatorFee'))
  return wei2eth(used * price + l1_fee + operator_fee)


@dataclass(frozen=True, kw_only=True)
class HistoryMixin(SDK):
  """Mixin for EVM history sources."""

  address: str
  node: NodeRpc
  rpc_url: str
  eoa_cache: dict[str, bool] = field(default_factory=dict[str, bool])

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.node

  @property
  def w3(self):
    """Return the configured Web3 instance."""
    return self.node.w3

  @SDK.method
  @rpc.wrap_exceptions
  async def is_eoa(self, address: str) -> bool:
    """Check if an address is an EOA."""
    code = await self.w3.eth.get_code(Web3.to_checksum_address(address))
    return code.to_0x_hex() == '0x'

  async def is_eoa_cached(self, address: str) -> bool:
    """Check if an address is an EOA, cached."""
    if address not in self.eoa_cache:
      self.eoa_cache[address] = await self.is_eoa(address)
    return self.eoa_cache[address]

  async def parse_execution(self, tx: TxData, receipt: TxReceipt) -> EvmTx.Execution:
    """Parse contract execution metadata from a raw transaction."""
    input, to = tx.get('input'), tx.get('to')
    if input is None:
      hash = (hash := tx.get('hash')) and hash.to_0x_hex()
      raise ValueError(
        f'No input or to address in transaction: {hash}. Input: {input}. To: {to}'
      )
    return EvmTx.Execution(
      to=to and Web3.to_checksum_address(to),
      eoa=await self.is_eoa_cached(to) if to else False,
      input=input.to_0x_hex(),
      canceled=receipt['status'] == 0,
      logs=EvmTx.Log.parse_all(receipt['logs']),
    )

  @SDK.method
  @rpc.wrap_exceptions
  async def get_tx_receipt(self, hash: str) -> TxReceipt:
    """Fetch a transaction receipt from the configured node."""
    return await self.w3.eth.get_transaction_receipt(HexBytes(hash))

  @SDK.method
  @rpc.wrap_exceptions
  async def get_tx(self, hash: str) -> TxData:
    """Fetch a transaction by hash from the configured node."""
    return await self.w3.eth.get_transaction(HexBytes(hash))

  async def get_tx_data(self, hash: str) -> tuple[TxData, TxReceipt]:
    """Fetch a transaction and its receipt without leaving sibling tasks behind."""
    tx_task = asyncio.create_task(self.get_tx(hash))
    receipt_task = asyncio.create_task(self.get_tx_receipt(hash))
    async with managed_tasks((tx_task, receipt_task)):
      return await tx_task, await receipt_task

  def parse_fee(self, tx: TxData, receipt: TxReceipt) -> Fee | None:
    """Parse the transaction fee if the sender matches the configured address."""
    if (from_ := tx.get('from')) and same_address(from_, self.address):
      return Fee(amount=tx_fee(receipt), asset='native')

  def parse_native_transfer(
    self, *, from_: str | None, to: str | None, wei: int, internal: bool
  ) -> EvmTx.NativeTransfer | None:
    """Parse one native value movement, from this address's point of view.

    Returns `None` when nothing moved or when neither leg is this address: an internal
    call between two third parties can sit inside a transaction this address is part of.
    """
    if wei == 0:
      return None
    value = wei2eth(Decimal(wei))
    if to is not None and same_address(to, self.address):
      change, counterparty = value, from_
    elif from_ is not None and same_address(from_, self.address):
      change, counterparty = -value, to
    else:
      return None
    if counterparty is None:
      return None
    return EvmTx.NativeTransfer(
      counterparty=counterparty, change=change, internal=internal
    )

  def parse_native_transfers(self, tx: TxData) -> list[EvmTx.NativeTransfer]:
    """Parse the outer native transfer of a transaction, if it carries value."""
    transfer = self.parse_native_transfer(
      from_=tx.get('from'),
      to=tx.get('to'),
      wei=int(tx.get('value') or 0),
      internal=False,
    )
    return [transfer] if transfer is not None else []
