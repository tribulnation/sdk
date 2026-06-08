from typing_extensions import Any, TypedDict, NotRequired
from dataclasses import dataclass
from decimal import Decimal
import asyncio

from web3 import Web3
from web3.types import TxReceipt, TxData, _Hash32, Wei
from ethereum import NodeRpc

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import EvmTx, Fee
from tribulnation.ethereum.core import rpc, wei2eth, same_address

def wei_field(value: Any) -> Decimal:
  """Return a wei-valued receipt field as a decimal integer."""
  if value is None:
    return Decimal('0')
  if isinstance(value, str) and value.startswith('0x'):
    return Decimal(int(value, 16))
  return Decimal(value)

class ValueFields(TypedDict):
  value: int | str | Wei

def tx_value(tx: ValueFields) -> Decimal:
  """Return the value of a transaction."""
  value = tx['value']
  return wei2eth(Decimal(value))

class FeeFields(TypedDict):
  gasUsed: int
  effectiveGasPrice: int
  l1Fee: NotRequired[int]
  operatorFee: NotRequired[int]

def tx_fee(tx: FeeFields) -> Decimal:
  """Return the full transaction fee in native units."""
  used = wei_field(tx['gasUsed'])
  price = wei_field(tx['effectiveGasPrice'])
  l1_fee = wei_field(tx.get('l1Fee'))
  operator_fee = wei_field(tx.get('operatorFee'))
  if l1_fee or operator_fee:
    print('L1 fee or operator fee', l1_fee, operator_fee)
  return wei2eth(used * price + l1_fee + operator_fee)

def parse_execution(tx: TxData) -> EvmTx.Execution | None:
  """Parse contract execution metadata from a raw transaction."""
  if (input := tx.get('input')) and (to := tx.get('to')):
    return EvmTx.Execution(
      contract_address=Web3.to_checksum_address(to),
      input=input.to_0x_hex(),
    )

TransferFields = TypedDict('TransferFields', {'value': str, 'to': str, 'from': str})

@dataclass(frozen=True, kw_only=True)
class HistoryMixin:
  """Mixin for EVM history sources."""
  address: str
  node: NodeRpc
  rpc_url: str

  async def __aenter__(self):
    await self.node.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.node.__aexit__(exc_type, exc_value, traceback)

  @property
  def w3(self):
    """Return the configured Web3 instance."""
    return self.node.w3

  @SDK.method
  @rpc.wrap_exceptions
  async def get_tx_receipt(self, hash: _Hash32 | str) -> TxReceipt:
    """Fetch a transaction receipt from the configured node."""
    return await self.w3.eth.get_transaction_receipt(hash) # type: ignore

  @SDK.method
  @rpc.wrap_exceptions
  async def get_tx(self, hash: _Hash32 | str) -> TxData:
    """Fetch a transaction by hash from the configured node."""
    return await self.w3.eth.get_transaction(hash) # type: ignore

  async def get_tx_data(self, hash: _Hash32 | str):
    return await asyncio.gather(
      self.get_tx(hash),
      self.get_tx_receipt(hash),
    )

  def parse_fee(self, tx: TxData, receipt: TxReceipt) -> Fee | None:
    """Parse the transaction fee from a receipt, if the from address matches the configured address."""
    if (from_ := tx.get('from')) and same_address(from_, self.address):
      return Fee(amount=tx_fee(receipt), asset='native') # type: ignore

  def parse_native_transfer(self, tx: ValueFields, *, internal: bool) -> EvmTx.NativeTransfer | None:
    """Parse a native transfer from a transaction."""
    to, from_ = tx['to'], tx['from'] # type: ignore
    if (value := tx_value(tx)) > 0:
      if same_address(to, self.address):
        amount = value
        counterparty = from_
      elif same_address(from_, self.address):
        amount = -value
        counterparty = to
      else:
        return None
      return EvmTx.NativeTransfer(
        counterparty=counterparty,
        change=amount,
        internal=internal,
      )

  def parse_native_transfers(self, tx: ValueFields) -> list[EvmTx.NativeTransfer]:
    """Parse native transfers from a transaction."""
    if transfer := self.parse_native_transfer(tx, internal=False):
      return [transfer]
    else:
      return []