from typing_extensions import Literal, Union, Any, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass(kw_only=True)
class BaseOperation:
  details: Any | None = None

@dataclass(kw_only=True)
class Other(BaseOperation):
  kind: Literal['other'] = 'other'

@dataclass
class Fee:
  amount: Decimal
  asset: str

@dataclass(kw_only=True)
class Trade(BaseOperation):
  kind: Literal['trade'] = 'trade'
  base: str
  quote: str
  qty: Decimal
  """Base asset quantity."""
  price: Decimal
  liquidity: Literal['MAKER', 'TAKER']
  side: Literal['BUY', 'SELL']
  fee: Fee | None = None

@dataclass(kw_only=True)
class SinglePostingOperation(BaseOperation):
  asset: str
  qty: Decimal

@dataclass(kw_only=True)
class Yield(SinglePostingOperation):
  kind: Literal['yield'] = 'yield'

@dataclass(kw_only=True)
class PerpetualFunding(SinglePostingOperation):
  kind: Literal['perpetual_funding'] = 'perpetual_funding'

@dataclass(kw_only=True)
class PerpetualSettlement(SinglePostingOperation):
  kind: Literal['perpetual_settlement'] = 'perpetual_settlement'

@dataclass(kw_only=True)
class Deposit(SinglePostingOperation):
  ...

@dataclass(kw_only=True)
class CryptoDeposit(Deposit):
  """Deposit from a blockchain."""
  kind: Literal['crypto_deposit'] = 'crypto_deposit'
  network: str
  tx_hash: str
  idx: int | None = None
  """Index of the event within the same transaction."""

@dataclass(kw_only=True)
class FiatDeposit(Deposit):
  kind: Literal['fiat_deposit'] = 'fiat_deposit'
  method: str
  fiat_currency: str
  """Fiat currency used to buy the asset."""
  fiat_amount: Decimal
  """Amount of the fiat currency used to buy the asset."""

@dataclass(kw_only=True)
class Withdrawal(SinglePostingOperation):
  fee: Fee | None = None

@dataclass(kw_only=True)
class CryptoWithdrawal(Withdrawal):
  """Withdrawal into a blockchain."""
  kind: Literal['crypto_withdrawal'] = 'crypto_withdrawal'
  network: str
  tx_hash: str
  idx: int | None = None
  """Index of the event within the same transaction."""
  address: str
  memo: str | None = None

@dataclass(kw_only=True)
class FiatWithdrawal(Withdrawal):
  kind: Literal['fiat_withdrawal'] = 'fiat_withdrawal'
  method: str
  fiat_currency: str
  """Fiat currency received."""
  fiat_amount: Decimal
  """Amount of the fiat currency received."""

@dataclass(kw_only=True)
class Bonus(SinglePostingOperation):
  kind: Literal['bonus'] = 'bonus'

@dataclass(kw_only=True)
class InternalTransfer(SinglePostingOperation):
  kind: Literal['internal_transfer'] = 'internal_transfer'
  from_account: str
  to_account: str

@dataclass(kw_only=True)
class BaseEthereumTransaction(BaseOperation):
  from_address: str
  tx_hash: str
  # idx: int | None = None
  # """Index of the event within the same transaction."""
  chain_id: int
  """Chain ID (see https://chainid.network/)"""

@dataclass(kw_only=True)
class EthereumTransaction(BaseEthereumTransaction):
  kind: Literal['ethereum_transfer'] = 'ethereum_transfer'
  to_address: str
  value: Decimal
  """Value sent [ETH]"""
  fee: Decimal
  """Fee paid [ETH]"""

@dataclass(kw_only=True)
class ERC20Transfer(BaseEthereumTransaction):
  kind: Literal['erc20_transfer'] = 'erc20_transfer'
  contract_address: str
  recipient_address: str
  value: Decimal
  """Value sent [Token]"""
  
Operation = Union[
  Other,
  Trade,
  Yield,
  PerpetualFunding,
  PerpetualSettlement,
  Deposit,
  CryptoDeposit, FiatDeposit,
  Withdrawal, CryptoWithdrawal, FiatWithdrawal,
  Bonus, InternalTransfer,
  EthereumTransaction, ERC20Transfer,
]

@dataclass(kw_only=True)
class BasePosting:
  asset: str
  change: Decimal

  def __format__(self, fmt: str) -> str:
    s = '+' if self.change > 0 else ''
    return f'{s}{self.change:{fmt}} {self.asset}'

  def __str__(self) -> str:
    return f'{self}'

@dataclass(kw_only=True)
class CurrencyPosting(BasePosting):
  kind: Literal['currency'] = 'currency'

@dataclass(kw_only=True)
class FuturePosting(BasePosting):
  kind: Literal['future'] = 'future'
  price: Decimal

@dataclass(kw_only=True)
class StrategyPosting(BasePosting):
  kind: Literal['strategy'] = 'strategy'

Posting = CurrencyPosting | FuturePosting | StrategyPosting

@dataclass(kw_only=True)
class Transaction:
  id: str
  time: datetime
  operation: Operation
  postings: Sequence[Posting]

@dataclass(kw_only=True)
class BaseSnapshot:
  asset: str
  time: datetime
  qty: Decimal

@dataclass(kw_only=True)
class CurrencySnapshot(BaseSnapshot):
  kind: Literal['currency'] = 'currency'

@dataclass(kw_only=True)
class FutureSnapshot(BaseSnapshot):
  kind: Literal['future'] = 'future'
  avg_price: Decimal
  """Average entry price"""

@dataclass(kw_only=True)
class StrategySnapshot(BaseSnapshot):
  kind: Literal['strategy'] = 'strategy'

Snapshot = CurrencySnapshot | FutureSnapshot | StrategySnapshot