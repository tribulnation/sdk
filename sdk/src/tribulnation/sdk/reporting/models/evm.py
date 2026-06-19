from typing_extensions import Literal, Sequence, Annotated, ClassVar
from decimal import Decimal
import pydantic
from .common import BaseObservation, Fee

def to_checksum_address(address: str) -> str:
  from web3 import Web3
  return Web3.to_checksum_address(address)

ChecksumAddress = Annotated[str, pydantic.AfterValidator(to_checksum_address)]

class BaseEvmTransfer(pydantic.BaseModel):
  change: Decimal
  counterparty: ChecksumAddress

class NativeEvmTransfer(BaseEvmTransfer):
  kind: Literal['native'] = 'native'
  internal: bool

class ERC20Transfer(BaseEvmTransfer):
  kind: Literal['erc20'] = 'erc20'
  asset: ChecksumAddress

EvmTransfer = NativeEvmTransfer | ERC20Transfer

class EvmTx(BaseObservation):
  """EVM-compatible blockchain transaction observation."""
  type: Literal['evm_tx'] = 'evm_tx'

  class Execution(pydantic.BaseModel):
    to: ChecksumAddress
    """To address"""
    input: str
    """Input data (if any)"""
    eoa: bool
    """Whether the `to` address is an EOA or a contract"""
    canceled: bool

  tx_id: str
  execution: Execution
  transfers: Sequence[EvmTransfer] = []
  fee: Fee | None = None

  Transfer: ClassVar = EvmTransfer