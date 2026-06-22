from typing_extensions import Literal, Sequence, Annotated
from types import UnionType
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


class EvmTx(BaseObservation):
  """EVM-compatible blockchain transaction observation."""
  model_config = {'ignored_types': (UnionType,)} # type: ignore
  type: Literal['evm_tx'] = 'evm_tx'
  
  class NativeTransfer(BaseEvmTransfer):
    kind: Literal['native'] = 'native'
    internal: bool
    asset: Literal['native'] = 'native'

  class ERC20Transfer(BaseEvmTransfer):
    kind: Literal['erc20'] = 'erc20'
    asset: ChecksumAddress

  Transfer = NativeTransfer | ERC20Transfer

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
  transfers: Sequence['EvmTx.Transfer'] = []
  fee: Fee | None = None
