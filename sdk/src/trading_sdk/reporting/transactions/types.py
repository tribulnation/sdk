from typing_extensions import Literal, TypeVar, Any, Sequence, Union, Generic, Annotated
from dataclasses import dataclass, replace, field
from decimal import Decimal
from datetime import datetime

D = TypeVar('D', default=Any, covariant=True)
D2 = TypeVar('D2', default=Any, covariant=True)

Label = Literal[
  'trade', 'yield', 'fee', 'bonus', 'other', 'internal_transfer',
  'future_trade', 'settlement', 'settlement_fee', 'funding',
  'strategy_deposit', 'strategy_withdrawal',
  'crypto_deposit', 'fiat_deposit', 'crypto_withdrawal', 'fiat_withdrawal', 'withdrawal_fee',
  'ethereum_transfer', 'erc20_transfer',
]

@dataclass(kw_only=True, frozen=True)
class Flow(Generic[D]):
  Label = Label
  kind: Literal['currency', 'future', 'strategy'] | None = None
  asset: str
  change: Decimal
  label: Label
  time: datetime
  price: Decimal | None = None
  details: D

@dataclass(kw_only=True, frozen=True)
class BaseEvent(Generic[D]):
  id: str
  time: datetime
  details: D

  @property
  def expected_flows(self) -> Sequence[Flow[D]]:
    """Flows expected to be matched."""
    return []

  @property
  def fixed_flows(self) -> Sequence[Flow[D]]:
    """Flows not appearing in the flows list but that should be included in the event."""
    return []

  @property
  def flows(self) -> Sequence[Flow[D]]:
    return list(self.expected_flows) + list(self.fixed_flows)


@dataclass(frozen=True)
class Fee:
  amount: Decimal
  asset: str

def sign(side: Literal['buy', 'sell']) -> Literal[1, -1]:
  match side:
    case 'buy': return 1
    case 'sell': return -1
    case _: raise ValueError(f'Unknown side: {side}')

@dataclass(kw_only=True, frozen=True)
class Trade(BaseEvent[D], Generic[D]):
  type: Literal['trade'] = field(default='trade')
  base: str
  quote: str
  qty: Decimal
  """Base asset quantity."""
  price: Decimal
  liquidity: Literal['maker', 'taker']
  side: Literal['buy', 'sell']
  fee: Fee | None = None

  @property
  def expected_flows(self) -> list[Flow[D]]:
    s = sign(self.side)
    flows = [
      Flow(
        time=self.time,
        label='trade',
        asset=self.base,
        change=s * self.qty,
        details=self.details,
        kind='currency',
      ),
      Flow(
        time=self.time,
        label='trade',
        asset=self.quote,
        change=-s * self.qty * self.price,
        details=self.details,
        kind='currency',
      ),
    ]
    if self.fee is not None:
      flows.append(Flow(
        time=self.time,
        label='fee',
        asset=self.fee.asset,
        change=-self.fee.amount,
        details=self.details,
        kind='currency',
      ))
    return flows
    

@dataclass(kw_only=True, frozen=True)
class FutureTrade(BaseEvent[D], Generic[D]):
  type: Literal['future_trade'] = field(default='future_trade')
  instrument: str
  size: Decimal
  price: Decimal
  liquidity: Literal['maker', 'taker']
  side: Literal['buy', 'sell']
  fee: Fee | None = None

  @property
  def expected_flows(self) -> list[Flow[D]]:
    if self.fee is not None:
      return [
        Flow(
          time=self.time,
          label='fee',
          asset=self.fee.asset,
          change=-self.fee.amount,
          details=self.details,
          kind='currency',
        ),
      ]
    else:
      return []

  @property  
  def fixed_flows(self) -> list[Flow[D]]:
    s = sign(self.side)
    return [
      Flow(
        time=self.time,
        label='future_trade',
        asset=self.instrument,
        change=s*self.size,
        price=self.price,
        details=self.details,
        kind='future',
      )
    ]

@dataclass(kw_only=True, frozen=True)
class SingleEvent(BaseEvent[D], Generic[D]):
  asset: str
  qty: Decimal
  type: Flow.Label

  @property
  def expected_flows(self) -> list[Flow[D]]:
    return [
      Flow(
        time=self.time,
        label=self.type,
        asset=self.asset,
        change=self.qty,
        details=self.details,
        kind='currency',
      )
    ]

  @classmethod
  def of(cls, id: str, flow: Flow[D2]) -> 'Event[D2]':
    match flow.label:
      case 'yield': cls = Yield
      case 'bonus': cls = Bonus
      case 'funding': cls = Funding
      case 'settlement': cls = Settlement
      case 'fee': cls = FeeEvent
      case 'internal_transfer': cls = InternalTransfer
      case 'other': cls = Other
      case 'strategy_deposit' | 'strategy_withdrawal':
        return Strategy(type=flow.label, id=id, time=flow.time, asset=flow.asset, qty=flow.change, details=flow.details)
      case _: raise ValueError(f'Unknown operation type: {flow.label}')
    return cls(id=id, time=flow.time, asset=flow.asset, qty=flow.change, details=flow.details)


@dataclass(kw_only=True, frozen=True)
class FeeEvent(SingleEvent[D], Generic[D]):
  type: Literal['fee'] = field(default='fee')

@dataclass(kw_only=True, frozen=True)
class InternalTransfer(SingleEvent[D], Generic[D]):
  type: Literal['internal_transfer'] = field(default='internal_transfer')

@dataclass(kw_only=True, frozen=True)
class Strategy(SingleEvent[D], Generic[D]):
  """Deposit into or withdraw from a strategy (E.g. trading bot, copy trading, etc.)"""
  strategy: str | None = None
  type: Literal['strategy_deposit', 'strategy_withdrawal']

  @property
  def fixed_flows(self) -> list[Flow[D]]:
    return [
      Flow(
        time=self.time,
        label=self.type,
        asset=self.strategy or self.asset,
        kind='strategy',
        change=-self.qty,
        details=self.details,
      )
    ]

@dataclass(kw_only=True, frozen=True)
class Yield(SingleEvent[D], Generic[D]):
  type: Literal['yield'] = field(default='yield')

@dataclass(kw_only=True, frozen=True)
class Other(SingleEvent[D], Generic[D]):
  type: Literal['other'] = field(default='other')

@dataclass(kw_only=True, frozen=True)
class Bonus(SingleEvent[D], Generic[D]):
  type: Literal['bonus'] = field(default='bonus')

@dataclass(kw_only=True, frozen=True)
class Funding(SingleEvent[D], Generic[D]):
  type: Literal['funding'] = field(default='funding')

@dataclass(kw_only=True, frozen=True)
class Settlement(SingleEvent[D], Generic[D]):
  type: Literal['settlement'] = field(default='settlement')

@dataclass(kw_only=True, frozen=True)
class CryptoDeposit(SingleEvent[D], Generic[D]):
  """Deposit from a blockchain."""
  type: Literal['crypto_deposit'] = field(default='crypto_deposit')
  network: str
  tx_hash: str
  idx: int | None = None
  """Index of the event within the same transaction."""

@dataclass(kw_only=True, frozen=True)
class FiatDeposit(SingleEvent[D], Generic[D]):
  type: Literal['fiat_deposit'] = field(default='fiat_deposit')
  method: str
  fiat_currency: str
  """Fiat currency used to buy the asset."""
  fiat_amount: Decimal
  """Amount of the fiat currency used to buy the asset."""

@dataclass(kw_only=True, frozen=True)
class Withdrawal(SingleEvent[D], Generic[D]):
  fee: Fee | None = None

  @property
  def expected_flows(self) -> list[Flow[D]]:
    flows = [
      Flow(
        time=self.time,
        label=self.type,
        asset=self.asset,
        change=-self.qty,
        details=self.details,
        kind='currency',
      )
    ]
    if self.fee is not None:
      flows.append(Flow(
        time=self.time,
        label='withdrawal_fee',
        asset=self.fee.asset,
        change=-self.fee.amount,
        details=self.details,
        kind='currency',
      ))
    return flows

@dataclass(kw_only=True, frozen=True)
class CryptoWithdrawal(Withdrawal[D], Generic[D]):
  """Withdrawal into a blockchain."""
  type: Literal['crypto_withdrawal'] = field(default='crypto_withdrawal')
  network: str
  tx_hash: str
  idx: int | None = None
  """Index of the event within the same transaction."""
  address: str
  memo: str | None = None

@dataclass(kw_only=True, frozen=True)
class FiatWithdrawal(Withdrawal[D], Generic[D]):
  type: Literal['fiat_withdrawal'] = field(default='fiat_withdrawal')
  method: str
  fiat_currency: str
  """Fiat currency received."""
  fiat_amount: Decimal
  """Amount of the fiat currency received."""


@dataclass(kw_only=True, frozen=True)
class BaseEthereumTransaction(BaseEvent[D], Generic[D]):
  tx_hash: str
  from_address: str
  to_address: str
  chain_id: int
  """Chain ID (see https://chainid.network/)"""

@dataclass(kw_only=True, frozen=True)
class EthereumTransaction(BaseEthereumTransaction[D], Generic[D]):
  type: Literal['ethereum_transfer'] = field(default='ethereum_transfer')
  value: Decimal
  """Value sent [ETH]"""
  fee: Decimal | None = None
  """Fee paid [ETH]"""

  @property
  def expected_flows(self) -> list[Flow[D]]:
    flows: list[Flow[D]] = []
    if self.value:
      flows.append(Flow(
        time=self.time,
        label='ethereum_transfer',
        asset='ETH',
        change=self.value,
        details=self.details,
        kind='currency',
      ))
    if self.fee is not None:
      flows.append(Flow(
        time=self.time,
        label='fee',  
        asset='ETH',
        change=-self.fee,
        details=self.details,
        kind='currency',
      ))
    return flows

@dataclass(kw_only=True, frozen=True)
class ERC20Transfer(BaseEthereumTransaction[D], Generic[D]):
  @dataclass
  class Transfer:
    sender_address: str
    recipient_address: str
    contract_address: str
    value: Decimal
    """Value sent [Token]"""
    direction: Literal['IN', 'OUT']

  type: Literal['erc20_transfer'] = field(default='erc20_transfer')
  fee: Decimal | None = None
  """Fee paid [ETH]"""
  transfers: Sequence[Transfer]

  @property
  def expected_flows(self) -> list[Flow[D]]:
    flows = [
      Flow(
        time=self.time,
        label='erc20_transfer',
        asset=transfer.contract_address,
        change=transfer.value * (1 if transfer.direction == 'IN' else -1),
        details=self.details,
        kind='currency',
      )
      for transfer in self.transfers
    ]
    if self.fee:
      flows.append(Flow(
        time=self.time,
        label='fee',
        asset='ETH',
        change=-self.fee,
        details=self.details,
        kind='currency',
      ))
    return flows

Event = Union[
  Trade[D], FutureTrade[D], Strategy[D], InternalTransfer[D],
  Yield[D], Bonus[D], Funding[D], Settlement[D], Other[D], FeeEvent[D],
  CryptoDeposit[D], FiatDeposit[D], CryptoWithdrawal[D], FiatWithdrawal[D],
  EthereumTransaction[D], ERC20Transfer[D],
]

@dataclass(kw_only=True, frozen=True)
class Transaction(Generic[D]):
  event: Event[D]
  flows: Sequence[Flow[D]]

  @property
  def time(self):
    return self.event.time

  def replace_time(self, time: datetime) -> 'Transaction[D]':
    return replace(
      self, event=replace(self.event, time=time),
      flows=[replace(p, time=time) for p in self.flows]
    )

  @staticmethod
  def single(id: str, flow: Flow[D2]) -> 'Transaction[D2]':
    event = SingleEvent[D2].of(id, flow)
    return Transaction(event=event, flows=[flow] + list(event.fixed_flows))