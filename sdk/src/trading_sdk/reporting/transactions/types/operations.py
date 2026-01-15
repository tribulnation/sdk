from typing_extensions import Literal, Any, Union
from dataclasses import dataclass
from decimal import Decimal

@dataclass(kw_only=True)
class BaseOperation:
  details: Any | None = None

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
  CryptoDeposit, FiatDeposit,
  CryptoWithdrawal, FiatWithdrawal,
  Bonus, InternalTransfer,
  EthereumTransaction, ERC20Transfer,
]