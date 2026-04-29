from typing_extensions import Literal, Annotated, Union
from datetime import datetime
from decimal import Decimal
import pydantic

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
]


class Flow(pydantic.BaseModel):
  id: str | None = None
  """Unique identifier, if provided by the source."""
  asset: str
  """Raw asset identifier, as provided by the source."""
  change: Decimal
  time: datetime
  event_id: str | None = None
  """Raw identifier of the causing event, if provided by the source."""
  event_type: EventType | None = None
  """Normalized event type, if known."""


class BaseEvent(pydantic.BaseModel):
  id: str | None = None
  """Unique identifier, if provided by the source."""
  time: datetime

class SpotTrade(BaseEvent):
  type: Literal['spot_trade'] = 'spot_trade'
  base: str
  """Raw base asset identifier, as provided by the source."""
  quote: str
  """Raw quote asset identifier, as provided by the source."""
  side: Literal['buy', 'sell']
  size: Decimal
  """Unsigned size in base asset units."""
  price: Decimal
  fee: Decimal | None = None
  fee_asset: str | None = None

class SingleFlowEvent(BaseEvent):
  amount: Decimal
  """Signed amount of the event, in the asset's base units."""
  asset: str
  """Raw asset identifier, as provided by the source."""

class Yield(SingleFlowEvent):
  type: Literal['yield'] = 'yield'

class Funding(SingleFlowEvent):
  type: Literal['funding'] = 'funding'

class Interest(SingleFlowEvent):
  type: Literal['interest'] = 'interest'

class Borrow(SingleFlowEvent):
  type: Literal['borrow'] = 'borrow'

class Repay(SingleFlowEvent):
  type: Literal['repay'] = 'repay'

class InternalTransfer(SingleFlowEvent):
  type: Literal['internal_transfer'] = 'internal_transfer'
  src_account: str | None = None
  dst_account: str | None = None

class CryptoDeposit(SingleFlowEvent):
  type: Literal['crypto_deposit']
  network: str | None = None
  """Raw network name, if provided by the source."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier, if explicitly provided by the source."""
  fee: Decimal | None = None
  fee_asset: str | None = None

class CryptoWithdrawal(SingleFlowEvent):
  type: Literal['crypto_withdrawal']
  network: str | None = None
  """Raw network name, if provided by the source."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier, if explicitly provided by the source."""
  fee: Decimal | None = None
  fee_asset: str | None = None


class FiatDeposit(SingleFlowEvent):
  type: Literal['fiat_deposit'] = 'fiat_deposit'
  fee: Decimal | None = None
  fee_asset: str | None = None

class FiatWithdrawal(SingleFlowEvent):
  type: Literal['fiat_withdrawal'] = 'fiat_withdrawal'
  fee: Decimal | None = None
  fee_asset: str | None = None

class CryptoTransfer(pydantic.BaseModel):
  tx_id: str
  """Blockchain transaction hash/identifier for the containing transaction."""
  idx: int | None = None
  asset: str
  amount: Decimal
  counterparty: str | None = None
  
class CryptoTransaction(BaseEvent):
  type: Literal['crypto_transaction'] = 'crypto_transaction'
  tx_id: str
  """Blockchain transaction hash/identifier."""
  transfers: list[CryptoTransfer]
  fee: Decimal | None = None
  fee_asset: str | None = None

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
    CryptoTransaction,
  ],
  pydantic.Discriminator('type')
]


class FileProvenance(pydantic.BaseModel):
  source: Literal['csv', 'excel']
  row: int
  file: str 

class DecisionProvenance(pydantic.BaseModel):
  source: Literal['decision']
  row: int
  file: str

Provenance = FileProvenance | DecisionProvenance

class History(pydantic.BaseModel):
  flows: list[Flow] = []
  events: list[Event] = []
  provenance: Provenance | None = None
