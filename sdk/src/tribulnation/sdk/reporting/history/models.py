from typing_extensions import Literal, Annotated, Union, Sequence, Any, TypedDict, NotRequired, ClassVar
from datetime import datetime
from decimal import Decimal
import pydantic

from tribulnation.sdk.reporting.snapshots import Snapshot

EventType = Literal[
  'trade',
  'yield',
  'funding',
  'interest',
  'borrow',
  'repay',
  'internal_transfer',
  'crypto_deposit',
  'crypto_withdrawal',
  'fiat_deposit',
  'fiat_withdrawal',
  'crypto_transaction',
  'evm_tx',
]


class Fee(pydantic.BaseModel):
  amount: Decimal
  """Amount paid."""
  asset: str
  """Raw asset identifier, as provided by the source."""


class Flow(pydantic.BaseModel):
  id: str | None = None
  """Unique identifier, if provided by the source."""
  asset: str
  """Raw asset identifier, as provided by the source."""
  change: Decimal
  time: datetime
  event_id: str | None = None
  """Raw identifier of the causing event, if provided by the source."""
  source_event_id: str | None = None
  """Raw identifier of the causing event, when distinct from `event_id`."""
  event_type: EventType | None = None
  """Normalized event type, if known."""


class BaseEvent(pydantic.BaseModel):
  type: EventType
  id: str | None = None
  """Unique identifier, if provided by the source."""
  source_id: str | None = None
  """Raw source identifier, when distinct from `id`."""
  time: datetime
  fee: Fee | None = None

  def flow(self, asset: str, change: Decimal) -> Flow:
    return Flow(
      asset=asset,
      change=change,
      time=self.time,
      event_id=self.id,
      event_type=self.type,
    )

  @property
  def flows(self) -> Sequence[Flow]:
    return []

class SpotTrade(BaseEvent):
  type: Literal['trade'] = 'trade' # type: ignore
  base: str
  """Raw base asset identifier, as provided by the source."""
  quote: str
  """Raw quote asset identifier, as provided by the source."""
  size: Decimal
  """Signed size in base asset units. Positive means bought, negative means sold."""
  price: Decimal
  """Quote asset units per base asset unit."""

  @property
  def flows(self) -> Sequence[Flow]:
    out: list[Flow] = [
      self.flow(self.base, self.size),
      self.flow(self.quote, -self.size * self.price),
    ]
    if self.fee:
      out.append(self.flow(self.fee.asset, -self.fee.amount))
    return out

class SingleFlowEvent(BaseEvent):
  amount: Decimal
  """Signed amount of the event, in the asset's base units."""
  asset: str
  """Raw asset identifier, as provided by the source."""

  @property
  def flows(self) -> Sequence[Flow]:
    return [self.flow(self.asset, self.amount)]

class Yield(SingleFlowEvent):
  type: Literal['yield'] = 'yield' # type: ignore

class Funding(SingleFlowEvent):
  type: Literal['funding'] = 'funding' # type: ignore

class Interest(SingleFlowEvent):
  type: Literal['interest'] = 'interest' # type: ignore

class Borrow(SingleFlowEvent):
  type: Literal['borrow'] = 'borrow' # type: ignore

class Repay(SingleFlowEvent):
  type: Literal['repay'] = 'repay' # type: ignore

class InternalTransfer(SingleFlowEvent):
  type: Literal['internal_transfer'] = 'internal_transfer' # type: ignore
  src_account: str | None = None
  dst_account: str | None = None

  @property
  def flows(self) -> Sequence[Flow]:
    return []

class CryptoDeposit(SingleFlowEvent):
  type: Literal['crypto_deposit'] = 'crypto_deposit' # type: ignore
  network: str | None = None
  """Raw network name, if provided by the source."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier, if explicitly provided by the source."""

class CryptoWithdrawal(SingleFlowEvent):
  type: Literal['crypto_withdrawal'] = 'crypto_withdrawal' # type: ignore
  network: str | None = None
  """Raw network name, if provided by the source."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier, if explicitly provided by the source."""
  dst_address: str | None = None
  """Destination address, if explicitly provided by the source."""


class FiatDeposit(SingleFlowEvent):
  type: Literal['fiat_deposit'] = 'fiat_deposit' # type: ignore

class FiatWithdrawal(SingleFlowEvent):
  type: Literal['fiat_withdrawal'] = 'fiat_withdrawal' # type: ignore

class CryptoTransfer(pydantic.BaseModel):
  asset: str
  """Raw asset identifier/address."""
  change: Decimal
  """Signed change in the asset's base units."""
  counterparty: str | None = None
  """Counterparty address, if known."""

class BaseCryptoTransaction(BaseEvent):
  """Generic blockchain transaction."""
  tx_id: str
  """Blockchain transaction hash/identifier."""
  transfers: Sequence[CryptoTransfer]

  @property
  def flows(self) -> Sequence[Flow]:
    flows = [
      self.flow(t.asset, t.change)
      for t in self.transfers
    ]
    if self.fee:
      flows.append(self.flow(self.fee.asset, -self.fee.amount))
    return flows

class CryptoTransaction(BaseCryptoTransaction):
  type: Literal['crypto_transaction'] = 'crypto_transaction' # type: ignore

class EvmTx(BaseCryptoTransaction):
  """EVM-compatible blockchain transaction."""
  type: Literal['evm_tx'] = 'evm_tx' # type: ignore
  
  class Execution(pydantic.BaseModel):
    contract_address: str
    """Contract address"""
    input: str | None = None
    """Input data (if any)"""
    method_name: str | None = None
    """Function called (if available)"""

  class NativeTransfer(CryptoTransfer):
    kind: Literal['native'] = 'native'
    internal: bool
    asset: str = 'native'

  class ERC20Transfer(CryptoTransfer):
    kind: Literal['erc20'] = 'erc20'

  Transfer: ClassVar = Union[NativeTransfer, ERC20Transfer]

  execution: Execution | None = None
  """Contract execution details (if any)"""
  transfers: Sequence[Transfer] = [] # type: ignore

Event = Annotated[
  Union[
    SpotTrade,
    Yield,
    Funding,
    Interest,
    Borrow,
    Repay,
    InternalTransfer,
    CryptoDeposit,
    CryptoWithdrawal,
    FiatDeposit,
    FiatWithdrawal,
    EvmTx,
    CryptoTransaction,
  ],
  pydantic.Discriminator('type')
]


class FileProvenance(TypedDict):
  source: Literal['csv', 'excel']
  row: int
  file: str 

class ApiProvenance(TypedDict):
  source: Literal['api']
  service: str
  endpoint: NotRequired[str]
  params: NotRequired[dict]
  response: NotRequired[Any]

class ManualProvenance(TypedDict):
  source: Literal['manual']
  label: NotRequired[str]
  note: NotRequired[str]
  ref: NotRequired[str]

Provenance = FileProvenance | ApiProvenance | ManualProvenance

class Record(pydantic.BaseModel):
  flows: Sequence[Flow] = []
  events: Sequence[Event] = []
  snapshots: Sequence[Snapshot] = []
  provenance: Provenance
