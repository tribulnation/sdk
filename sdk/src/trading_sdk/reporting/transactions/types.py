from typing_extensions import Literal, TypeVar, Any, Sequence, Union, Generic
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

D = TypeVar('D', default=Any, covariant=True)
D2 = TypeVar('D2', default=Any, covariant=True)

@dataclass(kw_only=True, frozen=True)
class Posting(Generic[D]):
  Type = Literal[
    'trade', 'yield', 'fee', 'bonus', 'other', 'internal_transfer',
    'future_trade', 'settlement', 'settlement_fee', 'funding',
    'strategy_deposit', 'strategy_withdrawal',
    'crypto_deposit', 'fiat_deposit', 'crypto_withdrawal', 'fiat_withdrawal', 'withdrawal_fee',
    'ethereum_transfer', 'erc20_transfer',
  ]
  
  asset: str
  change: Decimal
  kind: Literal['currency', 'future', 'strategy']
  type: Type
  time: datetime
  price: Decimal | None = None
  operationId: str | None = None
  details: D

@dataclass(kw_only=True, frozen=True)
class BaseOperation(Generic[D]):
  id: str
  time: datetime
  details: D

  @property
  def expected_postings(self) -> Sequence[Posting[D]]:
    """Postings expected to be matched."""
    return []

  @property
  def fixed_postings(self) -> Sequence[Posting[D]]:
    """Postings not appearing in the postings log but that should be included in the transaction."""
    return []


@dataclass(frozen=True)
class Fee:
  amount: Decimal
  asset: str

@dataclass(kw_only=True, frozen=True)
class Trade(BaseOperation[D], Generic[D]):
  type: Literal['trade'] = 'trade'
  base: str
  quote: str
  qty: Decimal
  """Base asset quantity."""
  price: Decimal
  liquidity: Literal['MAKER', 'TAKER']
  side: Literal['BUY', 'SELL']
  fee: Fee | None = None

  @property
  def expected_postings(self) -> list[Posting[D]]:
    s = 1 if self.side == 'BUY' else -1
    postings = [
      Posting(
        kind='currency',
        time=self.time,
        type='trade',
        asset=self.base,
        change=s * self.qty,
        details=self.details,
      ),
      Posting(
        kind='currency',
        time=self.time,
        type='trade',
        asset=self.quote,
        change=-s * self.qty * self.price,
        details=self.details,
      ),
    ]
    if self.fee is not None:
      postings.append(Posting(
        kind='currency',
        time=self.time,
        type='fee',
        asset=self.fee.asset,
        change=-self.fee.amount,
        details=self.details,
      ))
    return postings
    

@dataclass(kw_only=True, frozen=True)
class FutureTrade(BaseOperation[D], Generic[D]):
  type: Literal['future_trade'] = 'future_trade'
  asset: str
  size: Decimal
  price: Decimal
  liquidity: Literal['MAKER', 'TAKER']
  side: Literal['BUY', 'SELL']
  fee: Fee | None = None

  @property
  def expected_postings(self) -> list[Posting[D]]:
    if self.fee is not None:
      return [
        Posting(
          kind='currency',
          time=self.time,
          type='fee',
          asset=self.fee.asset,
          change=-self.fee.amount,
          details=self.details,
        ),
      ]
    else:
      return []

  @property  
  def fixed_postings(self) -> list[Posting[D]]:
    s = 1 if self.side == 'BUY' else -1
    return [
      Posting(
        kind='future',
        time=self.time,
        type='future_trade',
        asset=self.asset,
        change=s*self.size,
        price=self.price,
        details=self.details,
      )
    ]

@dataclass(kw_only=True, frozen=True)
class SinglePostingOperation(BaseOperation[D], Generic[D]):
  asset: str
  qty: Decimal
  type: Posting.Type

  @property
  def expected_postings(self) -> list[Posting[D]]:
    return [
      Posting(
        kind='currency',
        time=self.time,
        type=self.type,
        asset=self.asset,
        change=self.qty,
        details=self.details,
      )
    ]

  @classmethod
  def of(cls, id: str, posting: Posting[D2]) -> 'Operation[D2]':
    match posting.type:
      case 'yield': cls = Yield
      case 'bonus': cls = Bonus
      case 'funding': cls = Funding
      case 'settlement': cls = Settlement
      case 'strategy_deposit' | 'strategy_withdrawal': cls = Strategy
      case 'fee': cls = FeeOperation
      case 'internal_transfer': cls = InternalTransfer
      case 'other': cls = Other
      case _: raise ValueError(f'Unknown operation type: {posting.type}')
    return cls(id=id, time=posting.time, asset=posting.asset, qty=posting.change, type=posting.type, details=posting.details)


@dataclass(kw_only=True, frozen=True)
class FeeOperation(SinglePostingOperation[D], Generic[D]):
  type: Literal['fee'] = 'fee'

@dataclass(kw_only=True, frozen=True)
class InternalTransfer(SinglePostingOperation[D], Generic[D]):
  type: Literal['internal_transfer'] = 'internal_transfer'

@dataclass(kw_only=True, frozen=True)
class Strategy(SinglePostingOperation[D], Generic[D]):
  type: Literal['strategy_deposit', 'strategy_withdrawal']

  @property
  def fixed_postings(self) -> list[Posting[D]]:
    return [
      Posting(
        kind='currency',
        time=self.time,
        type=self.type,
        asset=self.asset,
        change=self.qty,
        details=self.details,
      ),
      Posting(
        kind='strategy',
        time=self.time,
        type=self.type,
        asset=self.asset,
        change=-self.qty,
        details=self.details,
      )
    ]


@dataclass(kw_only=True, frozen=True)
class Yield(SinglePostingOperation[D], Generic[D]):
  type: Literal['yield'] = 'yield'

@dataclass(kw_only=True, frozen=True)
class Other(SinglePostingOperation[D], Generic[D]):
  type: Literal['other'] = 'other'

@dataclass(kw_only=True, frozen=True)
class Bonus(SinglePostingOperation[D], Generic[D]):
  type: Literal['bonus'] = 'bonus'

@dataclass(kw_only=True, frozen=True)
class Funding(SinglePostingOperation[D], Generic[D]):
  type: Literal['funding'] = 'funding'

@dataclass(kw_only=True, frozen=True)
class Settlement(SinglePostingOperation[D], Generic[D]):
  type: Literal['settlement'] = 'settlement'

@dataclass(kw_only=True, frozen=True)
class CryptoDeposit(SinglePostingOperation[D], Generic[D]):
  """Deposit from a blockchain."""
  type: Literal['crypto_deposit'] = 'crypto_deposit'
  network: str
  tx_hash: str
  idx: int | None = None
  """Index of the event within the same transaction."""

@dataclass(kw_only=True, frozen=True)
class FiatDeposit(SinglePostingOperation[D], Generic[D]):
  type: Literal['fiat_deposit'] = 'fiat_deposit'
  method: str
  fiat_currency: str
  """Fiat currency used to buy the asset."""
  fiat_amount: Decimal
  """Amount of the fiat currency used to buy the asset."""

@dataclass(kw_only=True, frozen=True)
class Withdrawal(SinglePostingOperation[D], Generic[D]):
  fee: Fee | None = None

  @property
  def expected_postings(self) -> list[Posting[D]]:
    postings = [
      Posting(
        kind='currency',
        time=self.time,
        type=self.type,
        asset=self.asset,
        change=-self.qty,
        details=self.details,
      )
    ]
    if self.fee is not None:
      postings.append(Posting(
        kind='currency',
        time=self.time,
        type='withdrawal_fee',
        asset=self.fee.asset,
        change=-self.fee.amount,
        details=self.details,
      ))
    return postings

@dataclass(kw_only=True, frozen=True)
class CryptoWithdrawal(Withdrawal[D], Generic[D]):
  """Withdrawal into a blockchain."""
  type: Literal['crypto_withdrawal'] = 'crypto_withdrawal'
  network: str
  tx_hash: str
  idx: int | None = None
  """Index of the event within the same transaction."""
  address: str
  memo: str | None = None

@dataclass(kw_only=True, frozen=True)
class FiatWithdrawal(Withdrawal[D], Generic[D]):
  type: Literal['fiat_withdrawal'] = 'fiat_withdrawal'
  method: str
  fiat_currency: str
  """Fiat currency received."""
  fiat_amount: Decimal
  """Amount of the fiat currency received."""


@dataclass(kw_only=True, frozen=True)
class BaseEthereumTransaction(BaseOperation[D], Generic[D]):
  from_address: str
  tx_hash: str
  # idx: int | None = None
  # """Index of the event within the same transaction."""
  chain_id: int
  """Chain ID (see https://chainid.network/)"""

@dataclass(kw_only=True, frozen=True)
class EthereumTransaction(BaseEthereumTransaction[D], Generic[D]):
  type: Literal['ethereum_transfer'] = 'ethereum_transfer'
  to_address: str
  value: Decimal
  """Value sent [ETH]"""
  fee: Decimal
  """Fee paid [ETH]"""

  @property
  def expected_postings(self) -> list[Posting[D]]:
    return [
      Posting(
        kind='currency',
        time=self.time,
        type='ethereum_transfer',
        asset='ETH',
        change=self.value,
        details=self.details,
      ),
      Posting(
        kind='currency',
        time=self.time,
        type='fee',
        asset='ETH',
        change=-self.fee,
        details=self.details,
      ),
    ]

@dataclass(kw_only=True, frozen=True)
class ERC20Transfer(BaseEthereumTransaction[D], Generic[D]):
  type: Literal['erc20_transfer'] = 'erc20_transfer'
  contract_address: str
  recipient_address: str
  value: Decimal
  """Value sent [Token]"""

  @property
  def expected_postings(self) -> list[Posting[D]]:
    return [
      Posting(
        kind='currency',
        time=self.time,
        type='erc20_transfer',
        asset=self.contract_address,
        change=self.value,
        details=self.details,
      )
    ]

Operation = Union[
  Trade[D], FutureTrade[D], Strategy[D], InternalTransfer[D],
  Yield[D], Bonus[D], Funding[D], Settlement[D], Other[D],
  CryptoDeposit[D], FiatDeposit[D], CryptoWithdrawal[D], FiatWithdrawal[D],
  EthereumTransaction[D], ERC20Transfer[D],
]

@dataclass(kw_only=True, frozen=True)
class Transaction(Generic[D]):
  operation: Operation[D]
  postings: Sequence[Posting[D]]