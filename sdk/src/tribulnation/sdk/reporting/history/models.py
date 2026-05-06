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

ObservationType = Literal[
  'trade',
  'spot_order',
  'trade_leg',
  'fee',
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


class BaseObservation(pydantic.BaseModel):
  type: ObservationType
  id: str | None = None
  """Unique source identifier for this observation, if provided."""
  source_id: str | None = None
  """Raw source identifier, when distinct from `id`."""
  time: datetime | None = None
  fee: Fee | None = None


class Trade(BaseObservation):
  type: Literal['trade'] = 'trade' # type: ignore
  base: str | None = None
  """Raw base asset identifier, if provided by the source."""
  quote: str | None = None
  """Raw quote asset identifier, if provided by the source."""
  pair: str | None = None
  """Raw pair or market identifier, if provided by the source."""
  size: Decimal | None = None
  """Signed size in base asset units. Positive means bought, negative means sold."""
  price: Decimal | None = None
  """Quote asset units per base asset unit."""
  order_id: str | None = None
  trade_id: str | None = None


class SpotOrder(BaseObservation):
  type: Literal['spot_order'] = 'spot_order' # type: ignore
  order_id: str
  """Source order identifier. This is a correlation key, not a fill identity."""
  base: str | None = None
  """Raw base asset identifier, if provided by the source."""
  quote: str | None = None
  """Raw quote asset identifier, if provided by the source."""
  pair: str | None = None
  """Raw pair or market identifier, if provided by the source."""
  side: Literal['buy', 'sell'] | None = None
  status: str | None = None
  filled_size: Decimal | None = None
  """Executed base asset amount, stored as a positive quantity."""
  avg_price: Decimal | None = None
  """Average execution price in quote asset units per base asset unit."""
  quote_amount: Decimal | None = None
  """Executed quote asset notional, stored as a positive quantity."""


class TradeLeg(BaseObservation):
  type: Literal['trade_leg'] = 'trade_leg' # type: ignore
  asset: str
  """Raw asset identifier, as provided by the source."""
  amount: Decimal
  """Signed asset change."""
  pair: str | None = None
  order_id: str | None = None
  trade_id: str | None = None
  source_event_id: str | None = None


class FeeLeg(BaseObservation):
  type: Literal['fee'] = 'fee' # type: ignore
  asset: str
  """Raw fee asset identifier, as provided by the source."""
  amount: Decimal
  """Fee paid, stored as a positive amount."""
  event_type: EventType | None = None
  source_event_id: str | None = None


class SingleAssetObservation(BaseObservation):
  amount: Decimal
  """Signed amount of the observation, in the asset's base units."""
  asset: str
  """Raw asset identifier, as provided by the source."""


class Yield(SingleAssetObservation):
  type: Literal['yield'] = 'yield' # type: ignore


class Funding(SingleAssetObservation):
  type: Literal['funding'] = 'funding' # type: ignore


class Interest(SingleAssetObservation):
  type: Literal['interest'] = 'interest' # type: ignore


class Borrow(SingleAssetObservation):
  type: Literal['borrow'] = 'borrow' # type: ignore


class Repay(SingleAssetObservation):
  type: Literal['repay'] = 'repay' # type: ignore


class InternalTransfer(SingleAssetObservation):
  type: Literal['internal_transfer'] = 'internal_transfer' # type: ignore
  src_account: str | None = None
  dst_account: str | None = None


class CryptoDeposit(SingleAssetObservation):
  type: Literal['crypto_deposit'] = 'crypto_deposit' # type: ignore
  network: str | None = None
  """Raw network name, if provided by the source."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier, if explicitly provided by the source."""


class CryptoWithdrawal(SingleAssetObservation):
  type: Literal['crypto_withdrawal'] = 'crypto_withdrawal' # type: ignore
  network: str | None = None
  """Raw network name, if provided by the source."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier, if explicitly provided by the source."""
  dst_address: str | None = None
  """Destination address, if explicitly provided by the source."""


class FiatDeposit(SingleAssetObservation):
  type: Literal['fiat_deposit'] = 'fiat_deposit' # type: ignore


class FiatWithdrawal(SingleAssetObservation):
  type: Literal['fiat_withdrawal'] = 'fiat_withdrawal' # type: ignore


class CryptoTransfer(pydantic.BaseModel):
  asset: str
  """Raw asset identifier/address."""
  change: Decimal
  """Signed change in the asset's base units."""
  counterparty: str | None = None
  """Counterparty address, if known."""


class BaseCryptoTransaction(BaseObservation):
  """Generic blockchain transaction observation."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier."""
  transfers: Sequence[CryptoTransfer] = []


class CryptoTransaction(BaseCryptoTransaction):
  type: Literal['crypto_transaction'] = 'crypto_transaction' # type: ignore


class EvmTx(BaseCryptoTransaction):
  """EVM-compatible blockchain transaction observation."""
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


Observation = Annotated[
  Union[
    Trade,
    SpotOrder,
    TradeLeg,
    FeeLeg,
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

Event = Observation


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
  model_config = pydantic.ConfigDict(extra='forbid')

  observations: Sequence[Observation] = []
  snapshots: Sequence[Snapshot] = []
  provenance: Provenance
