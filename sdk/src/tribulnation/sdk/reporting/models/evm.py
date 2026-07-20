from typing_extensions import Literal, Sequence, Annotated, TYPE_CHECKING
from types import UnionType
from decimal import Decimal
import pydantic
from .common import BaseObservation, Fee

if TYPE_CHECKING:
  from web3.types import LogReceipt


def to_checksum_address(address: str) -> str:
  from web3 import Web3
  return Web3.to_checksum_address(address)

ChecksumAddress = Annotated[str, pydantic.AfterValidator(to_checksum_address)]


class Log(pydantic.BaseModel):
  address: ChecksumAddress
  data: str
  topics: list[str]

  @classmethod
  def parse(cls, log: 'LogReceipt'):
    return cls(
      address=log['address'],
      data=log['data'].to_0x_hex(),
      topics=[topic.to_0x_hex() for topic in log['topics']],
    )

  # class LogReceipt(TypedDict):
  #   address: ChecksumAddress
  #   blockHash: HexBytes
  #   blockNumber: BlockNumber
  #   data: HexBytes
  #   logIndex: int
  #   removed: bool
  #   topics: Sequence[HexBytes]
  #   transactionHash: HexBytes
  #   transactionIndex: int

  def dump(
    self, *, index: int = 0, block_number: int = 0, block_hash: str = '0x',
    transaction_hash: str = '0x', transaction_index: int = 0, removed: bool = False,
  ) -> 'LogReceipt':
    from web3.types import HexBytes, ChecksumAddress, BlockNumber # type: ignore
    return {
      'address': ChecksumAddress(self.address), # type: ignore
      'blockHash': HexBytes(block_hash),
      'blockNumber': BlockNumber(block_number),
      'data': HexBytes(self.data),
      'topics': [HexBytes(topic) for topic in self.topics],
      'transactionHash': HexBytes(transaction_hash),
      'transactionIndex': transaction_index,
      'logIndex': index,
      'removed': removed,
    }

  @classmethod
  def parse_all(cls, logs: Sequence['LogReceipt']) -> list['Log']:
    return [cls.parse(log) for log in sorted(logs, key=lambda log: log['logIndex'])]

class BaseEvmTransfer(pydantic.BaseModel):
  counterparty: ChecksumAddress
  change: Decimal

class EvmTx(BaseObservation):
  """EVM-compatible blockchain transaction observation."""
  model_config = {'ignored_types': (UnionType, type)} # type: ignore
  type: Literal['evm_tx'] = 'evm_tx'

  Log = Log

  class NativeTransfer(BaseEvmTransfer):
    kind: Literal['native'] = 'native'
    internal: bool
    
    @property
    def asset(self):
      return 'native'

  class ERC20Transfer(BaseEvmTransfer):
    kind: Literal['erc20'] = 'erc20'
    asset: ChecksumAddress

  class NftTransfer(BaseEvmTransfer):
    kind: Literal['nft'] = 'nft'
    contract_address: ChecksumAddress
    token_id: str

    @property
    def asset(self):
      return f'{self.contract_address}:{self.token_id}'
      

  Transfer = NativeTransfer | ERC20Transfer | NftTransfer

  class Execution(pydantic.BaseModel):
    to: ChecksumAddress | None
    """To address (can be None for contract creation)"""
    input: str
    """Input data (if any)"""
    eoa: bool
    """Whether the `to` address is an EOA or a contract"""
    canceled: bool
    logs: list['EvmTx.Log']

  tx_id: str
  execution: Execution
  transfers: Sequence['EvmTx.Transfer'] = []
  fee: Fee | None = None
