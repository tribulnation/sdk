from typing_extensions import Annotated, Union, Sequence, Literal
import pydantic
from .exchange import (
  SpotTrade, SpotOrder, TradeLeg, Conversion, FeeLeg,
  FutureTrade, FutureOrder, FuturePositionSummary, RealizedPnl,
  Yield, Bonus, Funding, Borrow, Repay, UnknownObservation,
  InternalTransfer, Transfer, CryptoDeposit, CryptoWithdrawal,
  FiatDeposit, FiatWithdrawal, FiatConversion,
)
from .blockchain import CryptoTransaction
from .evm import EvmTx
from .snapshots import Snapshot
from .provenance import Provenance

ObservationType = Literal[
  'spot_trade',
  'future_trade',
  'future_order',
  'future_position_summary',
  'realized_pnl',
  'spot_order',
  'trade_leg',
  'conversion',
  'fee',
  'yield',
  'bonus',
  'funding',
  'borrow',
  'repay',
  'internal_transfer',
  'transfer',
  'crypto_deposit',
  'crypto_withdrawal',
  'fiat_deposit',
  'fiat_withdrawal',
  'fiat_conversion',
  'crypto_transaction',
  'evm_tx',
  'unknown',
]

Observation = Annotated[
  Union[
    SpotTrade,
    FutureTrade,
    FutureOrder,
    FuturePositionSummary,
    RealizedPnl,
    SpotOrder,
    TradeLeg,
    Conversion,
    FeeLeg,
    Yield,
    Bonus,
    Funding,
    Borrow,
    Repay,
    InternalTransfer,
    Transfer,
    CryptoDeposit,
    CryptoWithdrawal,
    FiatDeposit,
    FiatWithdrawal,
    FiatConversion,
    EvmTx,
    CryptoTransaction,
    UnknownObservation,
  ],
  pydantic.Discriminator('type')
]

class Record(pydantic.BaseModel):
  model_config = pydantic.ConfigDict(extra='forbid')
  observations: Sequence[Observation] = []
  snapshots: Sequence[Snapshot] = []
  provenance: Provenance