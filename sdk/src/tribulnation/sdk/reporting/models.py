from types import UnionType
from typing_extensions import Literal, Annotated, Union, Sequence, Any, TypedDict, NotRequired, TypedDict
from datetime import datetime
from decimal import Decimal
import pydantic

class Balance(pydantic.BaseModel):
  qty: Decimal
  kind: Literal['currency', 'future', 'strategy']
  avg_price: Decimal | None = None
  """Average entry price"""

class Snapshot(pydantic.BaseModel):
  time: pydantic.AwareDatetime
  balances: dict[str, Balance]

  def amount(self, asset: str) -> Decimal:
    if (balance := self.balances.get(asset)):
      return balance.qty
    else:
      return Decimal('0')

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
  'unknown',
]

TradeLegEventType = Literal['spot_trade', 'conversion', 'fiat_conversion']

class Fee(pydantic.BaseModel):
  amount: Decimal = pydantic.Field(..., ge=0)
  """Amount paid."""
  asset: str
  """Raw asset identifier, as provided by the source."""

  def __str__(self) -> str:
    return f'Fee({self.amount} {self.asset})'

class BaseObservation(pydantic.BaseModel):
  id: str | None = None
  """Raw identifier, if provided by the source."""
  time: pydantic.AwareDatetime | None = None
  subaccount: str | None = None
  """Venue subaccount or compartment label, if the source row has a scoped account."""

class SpotTrade(BaseObservation):
  """An exchange of an asset for another, with an optional fee."""
  type: Literal['spot_trade'] = 'spot_trade'
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
  """Raw order identifier, if provided by the source."""
  fee: Fee | None = None
  """Fee paid, if any."""

  def __str__(self) -> str:
    return f'SpotTrade({self.size or "?"} @ {self.price or "?"} {self.base or "?"}/{self.quote or "?"}, {self.time}, fee: {self.fee or "-"})'

class FutureTrade(BaseObservation):
  """A futures or perpetual fill that changes derivative exposure."""
  type: Literal['future_trade'] = 'future_trade'
  instrument: str | None = None
  """Raw futures or perpetual instrument identifier."""
  base: str | None = None
  """Underlying/base asset, if known."""
  quote: str | None = None
  """Quote asset used for the instrument price, if known."""
  settle: str | None = None
  """Settlement asset for realized PnL, fees, and funding."""
  position_id: str | None = None
  """Raw futures position identifier, if provided by the source."""
  size: Decimal
  """Signed contract size. Positive increases long exposure; negative increases short exposure."""
  price: Decimal
  """Execution price in quote units."""
  realized_pnl: Decimal | None = None
  """Fill-level realized PnL in settlement asset units, excluding fees. If provided by the source."""
  order_id: str | None = None
  """Raw order identifier, if provided by the source."""
  fee: Fee | None = None
  """Fee paid, if any."""

class FutureOrder(BaseObservation):
  """A futures or perpetual order that can contextualize fill-level trades."""
  type: Literal['future_order'] = 'future_order'
  order_id: str | None = None
  """Raw order identifier, if provided by the source."""
  side: Literal['buy', 'sell'] | None = None
  """Order side, if provided by the source."""
  instrument: str | None = None
  """Raw futures or perpetual instrument identifier."""
  base: str | None = None
  """Underlying/base asset, if known."""
  quote: str | None = None
  """Quote asset used for the instrument price, if known."""
  settle: str | None = None
  """Settlement asset for realized PnL, fees, and funding."""
  position_id: str | None = None
  """Raw futures position identifier, if provided by the source."""
  status: str | None = None
  """Raw order status, if provided by the source."""
  filled_size: Decimal | None = None
  """Executed contract amount. Positive buy or negative sell when the source is signed."""
  avg_price: Decimal | None = None
  """Average execution price, if provided by the source."""
  fee: Fee | None = None
  """Fee paid, if any."""

class RealizedPnl(BaseObservation):
  """A source-provided realized PnL settlement observation."""
  type: Literal['realized_pnl'] = 'realized_pnl'
  instrument: str | None = None
  """Raw futures or perpetual instrument identifier."""
  asset: str
  """Settlement asset for realized PnL."""
  amount: Decimal
  """Signed realized PnL in settlement asset units."""
  position_id: str | None = None
  """Raw futures position identifier, if provided by the source."""
  order_id: str | None = None
  """Raw order identifier, if provided by the source."""
  trade_id: str | None = None
  """Raw trade/fill identifier, if provided by the source."""

class FuturePositionSummary(BaseObservation):
  """Aggregate futures position evidence without direct ledger impact."""
  type: Literal['future_position_summary'] = 'future_position_summary'
  position_id: str | None = None
  """Raw futures position identifier, if provided by the source."""
  instrument: str | None = None
  """Raw futures or perpetual instrument identifier."""
  base: str | None = None
  """Underlying/base asset, if known."""
  quote: str | None = None
  """Quote asset used for the instrument price, if known."""
  settle: str | None = None
  """Settlement asset for realized PnL, fees, and funding."""
  position_side: Literal['long', 'short'] | None = None
  """Position direction, when reported by the source."""
  margin_mode: str | None = None
  """Raw margin mode, such as isolated or cross, if reported."""
  opened_at: datetime | None = None
  """Source opening time for the summarized position interval."""
  closed_at: datetime | None = None
  """Source closing time for the summarized position interval."""
  opened_size: Decimal | None = None
  """Positive opened position amount, if provided by the source."""
  closed_size: Decimal | None = None
  """Positive closed position amount, if provided by the source."""
  closed_value: Decimal | None = None
  """Positive source-reported closed notional value, if provided."""
  avg_entry_price: Decimal | None = None
  """Average entry price for the summarized position."""
  avg_close_price: Decimal | None = None
  """Average close price for the summarized position."""
  realized_pnl: Decimal | None = None
  """Signed realized PnL in settlement asset units, excluding fees and funding."""
  funding: Decimal | None = None
  """Signed aggregate funding in settlement asset units."""
  total_fee: Decimal | None = None
  """Positive aggregate trading fee paid in settlement asset units."""
  opening_fee: Decimal | None = None
  """Positive opening trading fee component, if provided by the source."""
  closing_fee: Decimal | None = None
  """Positive closing trading fee component, if provided by the source."""
  position_pnl: Decimal | None = None
  """Signed source-reported net position PnL, if provided."""

class SpotOrder(BaseObservation):
  """A spot order (executed or not) for an asset pair, with an optional fee."""
  type: Literal['spot_order'] = 'spot_order'
  order_id: str | None = None
  """Raw order identifier, if provided by the source."""
  side: Literal['buy', 'sell'] | None = None
  """Order side, if provided by the source."""
  base: str | None = None
  """Raw base asset identifier, if provided by the source."""
  quote: str | None = None
  """Raw quote asset identifier, if provided by the source."""
  pair: str | None = None
  """Raw pair or market identifier, if provided by the source."""
  status: Literal['filled', 'partially_filled', 'cancelled'] | None = None
  """Order status, if provided by the source."""
  filled_size: Decimal | None = None
  """Executed base asset amount (positive for buy, negative for sell), if provided by the source."""
  avg_price: Decimal | None = None
  """Average execution price, if provided by the source."""
  fee: Fee | None = None
  """Fee paid, if any."""

class TradeLeg(BaseObservation):
  """A source balance leg that can support a trade or conversion batch."""
  type: Literal['trade_leg'] = 'trade_leg'
  asset: str
  """Raw asset identifier, as provided by the source."""
  amount: Decimal
  """Signed asset change."""
  pair: str | None = None
  order_id: str | None = None
  """Raw order identifier, if provided by the source."""
  trade_id: str | None = None
  """Raw trade identifier, if provided by the source."""
  event_type: TradeLegEventType | None = None
  """Leg semantic marker. Missing or trade means ordinary trade evidence."""
  label: str | None = None
  """Raw source operation label used for source-labeled grouping."""

  def __str__(self) -> str:
    return f'TradeLeg({self.amount} {self.asset}, {self.time}, event_type: {self.event_type or "?"}, label: {self.label or "?"})'

class ConversionLeg(pydantic.BaseModel):
  """A source-preserving leg inside a canonical conversion batch."""
  asset: str
  """Raw asset identifier, as provided by the source."""
  amount: Decimal
  """Signed asset balance change."""

class Conversion(BaseObservation):
  """Canonical grouped conversion without reliable pair/order identity."""
  type: Literal['conversion'] = 'conversion'
  legs: Sequence[ConversionLeg]
  """Signed source legs included in deterministic source order."""
  fee: Fee | None = None
  """Fee paid, if any."""

class FeeLeg(BaseObservation):
  """A fee leg of an event."""
  type: Literal['fee'] = 'fee'
  asset: str
  """Raw fee asset identifier, as provided by the source."""
  amount: Decimal
  """Raw source fee amount. Matching uses the absolute value."""
  event_type: ObservationType | None = None
  """Event/observation type, if provided by the source."""
  event_id: str | None = None
  """Event/observation identifier, if provided by the source."""

class SingleAssetObservation(BaseObservation):
  amount: Decimal
  """Signed amount of the observation, in the asset's base units."""
  asset: str
  """Raw asset identifier, as provided by the source."""

  def __str__(self) -> str:
    type = self.type # type: ignore
    return f'{type}: {self.amount} {self.asset} [{self.time}]'

class UnknownObservation(SingleAssetObservation):
  """A source observation whose economic meaning is intentionally unclassified."""
  type: Literal['unknown'] = 'unknown'

class Yield(SingleAssetObservation):
  """Inflow from staking, lending, etc."""
  type: Literal['yield'] = 'yield'

class Bonus(SingleAssetObservation):
  """Promotional credit, grant, recycle, expiry, revocation, or reversal."""
  type: Literal['bonus'] = 'bonus'
  category: str | None = None
  """Raw source category/action, if provided by the source."""

class Funding(SingleAssetObservation):
  """Funding received or paid for a perpetual contract position."""
  type: Literal['funding'] = 'funding'
  instrument: str | None = None
  """Raw futures or perpetual instrument identifier, if provided by the source."""
  position_id: str | None = None
  """Raw futures position identifier, if provided by the source."""

class Borrow(SingleAssetObservation):
  """Inflow from a loan."""
  type: Literal['borrow'] = 'borrow'

class Repay(SingleAssetObservation):
  """Outflow to repay a loan."""
  type: Literal['repay'] = 'repay'

class InternalTransfer(SingleAssetObservation):
  """Movement between compartments inside the current venue account scope."""
  type: Literal['internal_transfer'] = 'internal_transfer'
  amount: Decimal = pydantic.Field(..., ge=0)
  """Positive moved amount. Direction is described by src_account and dst_account."""
  src_account: str | None = None
  """Source compartment inside the current venue account scope, if known."""
  dst_account: str | None = None
  """Destination compartment inside the current venue account scope, if known."""

class Transfer(SingleAssetObservation):
  """Movement into or out of the current venue account scope."""
  type: Literal['transfer'] = 'transfer'
  amount: Decimal
  """Signed balance change from the current account perspective."""
  src_account: str | None = None
  """Raw source account label, if provided by the source."""
  dst_account: str | None = None
  """Raw destination account label, if provided by the source."""
  fee: Fee | None = None
  """Fee paid, if any."""

class BaseCryptoTransfer(SingleAssetObservation):
  network: str | None = None
  """Raw network identifier, if provided by the source."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier, if explicitly provided by the source."""
  src_address: str | None = None
  """Sending address, if explicitly provided by the source."""
  dst_address: str | None = None
  """Receiving address, if explicitly provided by the source."""
  fee: Fee | None = None
  """Fee paid, if any."""

class CryptoDeposit(BaseCryptoTransfer):
  """Inflow from depositing a crypto asset into an account."""
  type: Literal['crypto_deposit'] = 'crypto_deposit'

class CryptoWithdrawal(BaseCryptoTransfer):
  """Outflow from withdrawing a crypto asset from an account."""
  type: Literal['crypto_withdrawal'] = 'crypto_withdrawal'

class BaseFiatTransfer(SingleAssetObservation):
  fiat_asset: str | None = None
  """Raw spent fiat asset identifier, if provided by the source (and different from the credited asset)."""
  fee: Fee | None = None
  """Fee paid, if any."""

class FiatDeposit(BaseFiatTransfer):
  """Inflow from depositing a fiat asset into an account."""
  type: Literal['fiat_deposit'] = 'fiat_deposit'

class FiatWithdrawal(BaseFiatTransfer):
  """Outflow from withdrawing a fiat asset from an account."""
  type: Literal['fiat_withdrawal'] = 'fiat_withdrawal'

class FiatConversion(SingleAssetObservation):
  """Crypto balance change caused by an external fiat buy or sell."""
  type: Literal['fiat_conversion'] = 'fiat_conversion'
  amount: Decimal
  """Signed crypto account change. Positive means fiat buy; negative means fiat sell."""
  fiat_asset: str
  """Raw external fiat asset identifier, if provided by the source."""
  fiat_amount: Decimal
  """Signed external fiat amount, if provided by the source."""
  fee: Fee | None = None
  """External/payment fee metadata, if provided by the source."""
  payment_method: str | None = None
  """Raw external payment method, if provided by the source."""

class CryptoTransfer(pydantic.BaseModel):
  """A crypto asset transferred within a blockchain transaction."""
  asset: str
  """Raw asset identifier/address."""
  change: Decimal
  """Signed amount being transferred."""
  counterparty: str | None = None
  """Counterparty address, if known."""

class BaseCryptoTransaction(BaseObservation):
  type: Literal['crypto_transaction'] = 'crypto_transaction'
  """Generic blockchain transaction observation."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier."""
  fee: Fee | None = None
  """Fee paid, if any."""
  transfers: Sequence[CryptoTransfer] = []
  """Transfers occured within the transaction."""

class CryptoTransaction(BaseCryptoTransaction):
  """Generic blockchain transaction observation."""
  kind: Literal[None] = None

class EvmTx(BaseCryptoTransaction):
  """EVM-compatible blockchain transaction observation."""
  kind: Literal['evm'] = 'evm'

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

  model_config = {'ignored_types': (UnionType,)} # type: ignore (make Transfer not freak out pydantic)
  Transfer = NativeTransfer | ERC20Transfer
  execution: Execution | None = None
  """Contract execution details (if any)"""
  transfers: Sequence[NativeTransfer|ERC20Transfer] = [] # type: ignore

def observation_discriminator(obj):
  def get_attr(obj, attr):
    if isinstance(obj, dict):
      return obj.get(attr)
    else:
      return getattr(obj, attr, '')
  type = get_attr(obj, 'type')
  if type == 'crypto_transaction':
    kind = get_attr(obj, 'kind')
    if kind:
      type += f':{kind}'
  return type

Observation = Annotated[
  Union[
    Annotated[SpotTrade, pydantic.Tag('spot_trade')],
    Annotated[FutureTrade, pydantic.Tag('future_trade')],
    Annotated[FutureOrder, pydantic.Tag('future_order')],
    Annotated[FuturePositionSummary, pydantic.Tag('future_position_summary')],
    Annotated[RealizedPnl, pydantic.Tag('realized_pnl')],
    Annotated[SpotOrder, pydantic.Tag('spot_order')],
    Annotated[TradeLeg, pydantic.Tag('trade_leg')],
    Annotated[Conversion, pydantic.Tag('conversion')],
    Annotated[FeeLeg, pydantic.Tag('fee')],
    Annotated[Yield, pydantic.Tag('yield')],
    Annotated[Bonus, pydantic.Tag('bonus')],
    Annotated[Funding, pydantic.Tag('funding')],
    Annotated[Borrow, pydantic.Tag('borrow')],
    Annotated[Repay, pydantic.Tag('repay')],
    Annotated[InternalTransfer, pydantic.Tag('internal_transfer')],
    Annotated[Transfer, pydantic.Tag('transfer')],
    Annotated[CryptoDeposit, pydantic.Tag('crypto_deposit')],
    Annotated[CryptoWithdrawal, pydantic.Tag('crypto_withdrawal')],
    Annotated[FiatDeposit, pydantic.Tag('fiat_deposit')],
    Annotated[FiatWithdrawal, pydantic.Tag('fiat_withdrawal')],
    Annotated[FiatConversion, pydantic.Tag('fiat_conversion')],
    Annotated[EvmTx, pydantic.Tag('crypto_transaction:evm')],
    Annotated[CryptoTransaction, pydantic.Tag('crypto_transaction')],
    Annotated[UnknownObservation, pydantic.Tag('unknown')],
  ],
  pydantic.Discriminator(observation_discriminator)
]

class BaseProvenance(TypedDict):
  id: str
  """Unique identifier for all records sharing a same provenance."""
  details: NotRequired[Any]

class TabularProvenance(BaseProvenance):
  source: Literal['tabular']
  row: int
  file: str

class ApiProvenance(BaseProvenance):
  source: Literal['api']
  service: str

class ManualProvenance(BaseProvenance):
  source: Literal['manual']

class DerivedProvenance(BaseProvenance):
  source: Literal['derived']

Provenance = Annotated[
  TabularProvenance | ApiProvenance | ManualProvenance | DerivedProvenance,
  pydantic.Discriminator('source')
]

class Record(pydantic.BaseModel):
  model_config = pydantic.ConfigDict(extra='forbid')
  observations: Sequence[Observation] = []
  snapshots: Sequence[Snapshot] = []
  provenance: Provenance
