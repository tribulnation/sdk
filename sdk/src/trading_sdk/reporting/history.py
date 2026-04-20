from typing_extensions import Any, Literal, Sequence, AsyncIterable, Union
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from trading_sdk.core import SDK

@dataclass(kw_only=True, frozen=True)
class Flow:
  id: str | None = None
  asset: str
  change: Decimal
  price: Decimal | None = None
  time: datetime
  event_id: str | None = None
  event_tag: str | None = None
  raw: Any
  source: str

@dataclass(kw_only=True, frozen=True)
class BaseEvent:
  tag: str
  id: str | None = None
  time: datetime
  raw: Any
  source: str

  def flow(self, asset: str, change: Decimal, *, tag: str | None = None) -> Flow:
    return Flow(
      time=self.time,
      asset=asset,
      change=change,
      raw=self,
      event_id=self.id,
      event_tag=tag or self.tag,
      source=self.source,
    )

  @property
  def flows(self) -> Sequence[Flow]:
    return []

@dataclass(kw_only=True, frozen=True)
class SpotTrade(BaseEvent):
  tag: Literal['spot_trade'] = 'spot_trade'
  qty: Decimal
  price: Decimal
  base: str
  quote: str
  liquidity: Literal['maker', 'taker'] | None = None
  side: Literal['buy', 'sell']
  fee: Decimal | None = None
  fee_asset: str | None = None

  @property
  def flows(self) -> Sequence[Flow]:
    sign = 1 if self.side == 'buy' else -1
    flows: list[Flow] = [
      self.flow(self.base, sign * self.qty),
      self.flow(self.quote, -sign * self.qty * self.price),
    ]
    if self.fee and self.fee_asset:
      flows.append(self.flow(self.fee_asset, -self.fee))
    return flows

@dataclass(kw_only=True, frozen=True)
class FuturesTrade(BaseEvent):
  tag: Literal['futures_trade'] = 'futures_trade'
  qty: Decimal
  price: Decimal
  instrument: str
  liquidity: Literal['maker', 'taker'] | None = None
  side: Literal['buy', 'sell']
  fee: Decimal | None = None
  fee_asset: str | None = None

  @property
  def flows(self) -> Sequence[Flow]:
    sign = 1 if self.side == 'buy' else -1
    flows: list[Flow] = [
      self.flow(self.instrument, sign * self.qty),
    ]
    if self.fee and self.fee_asset:
      flows.append(self.flow(self.fee_asset, -self.fee))
    return flows

@dataclass(kw_only=True, frozen=True)
class CryptoDeposit(BaseEvent):
  tag: Literal['crypto_deposit'] = 'crypto_deposit'
  qty: Decimal
  asset: str
  network: str
  tx_hash: str
  idx: int | None = None
  memo: str | None = None

  @property
  def flows(self) -> Sequence[Flow]:
    return [self.flow(self.asset, self.qty)]

@dataclass(kw_only=True, frozen=True)
class CryptoWithdrawal(BaseEvent):
  tag: Literal['crypto_withdrawal'] = 'crypto_withdrawal'
  qty: Decimal
  asset: str
  network: str
  tx_hash: str
  idx: int | None = None
  fee: Decimal | None = None
  fee_asset: str | None = None
  dst_address: str
  dst_memo: str | None = None

  @property
  def flows(self) -> Sequence[Flow]:
    flows: list[Flow] = [self.flow(self.asset, -self.qty)]
    if self.fee and self.fee_asset:
      flows.append(self.flow(self.fee_asset, -self.fee))
    return flows

@dataclass(kw_only=True, frozen=True)
class FiatDeposit(BaseEvent):
  tag: Literal['fiat_deposit'] = 'fiat_deposit'
  asset: str
  qty: Decimal
  """Amount of the asset credited."""
  fiat_currency: str
  fiat_amount: Decimal
  """Amount of the fiat currency deposited."""
  method: str

  @property
  def flows(self) -> Sequence[Flow]:
    return [self.flow(self.asset, self.qty)]

@dataclass(kw_only=True, frozen=True)
class FiatWithdrawal(BaseEvent):
  tag: Literal['fiat_withdrawal'] = 'fiat_withdrawal'
  asset: str
  qty: Decimal
  """Amount of the asset debited."""
  fiat_currency: str
  fiat_amount: Decimal
  """Amount of the fiat currency withdrawn."""
  method: str

  @property
  def flows(self) -> Sequence[Flow]:
    return [self.flow(self.asset, -self.qty)]

@dataclass(kw_only=True, frozen=True)
class Yield(BaseEvent):
  tag: Literal['yield'] = 'yield'
  asset: str
  qty: Decimal

  @property
  def flows(self) -> Sequence[Flow]:
    return [self.flow(self.asset, self.qty)]

@dataclass(kw_only=True, frozen=True)
class EvmTx(BaseEvent):
  @dataclass(kw_only=True, frozen=True)
  class Execution:
    contract_address: str
    """Contract address"""
    input: str | None = None
    """Input data (if any)"""
    method_name: str | None = None
    """Function called (if available)"""

  @dataclass(kw_only=True, frozen=True)
  class BaseTransfer:
    direction: Literal['in', 'out']
    """Direction of the transfer"""
    counterparty: str
    """Counterparty address"""
    value: Decimal
    """Value"""
  
  @dataclass(kw_only=True, frozen=True)
  class NativeTransfer(BaseTransfer):
    kind: Literal['native'] = 'native'
    internal: bool

  @dataclass(kw_only=True, frozen=True)
  class ERC20Transfer(BaseTransfer):
    kind: Literal['erc20'] = 'erc20'
    contract_address: str
    """Contract address"""

    def __post_init__(self):
      from web3 import Web3
      assert Web3.is_checksum_address(self.contract_address)

  Transfer = Union[NativeTransfer, ERC20Transfer]

  tag: Literal['evm_tx'] = 'evm_tx'
  hash: str
  fee: Decimal | None = None
  """Fee paid [ETH]"""
  execution: Execution | None = None
  """Contract execution details (if any)"""
  transfers: Sequence[Transfer] = field(default_factory=list)
  """Transfers"""

  @property
  def flows(self) -> Sequence[Flow]:
    flows: list[Flow] = []
    for t in self.transfers:
      assert t.direction in ('in', 'out'), f'Invalid direction: {t.direction}'
      sign = 1 if t.direction == 'in' else -1
      value = sign * t.value
      if t.kind == 'native':
        flows.append(self.flow('native', value, tag='evm_tx:native'))
      elif t.kind == 'erc20':
        flows.append(self.flow(t.contract_address, value, tag='evm_tx:erc20')) # type: ignore (wtf)
      else:
        raise ValueError(f'Unknown transfer kind: {t.kind}')
    if self.fee:
      flows.append(self.flow('native', -self.fee, tag='evm_tx:fee'))
    return flows

Event = Union[
  SpotTrade, FuturesTrade, Yield,
  CryptoDeposit, CryptoWithdrawal,
  FiatDeposit, FiatWithdrawal,
  EvmTx,
]

class History(SDK):
  @dataclass(kw_only=True, frozen=True)
  class History:
    flows: Sequence[Flow] = field(default_factory=list)
    events: Sequence[Event] = field(default_factory=list)

  @SDK.method
  @abstractmethod
  def history(self, start: datetime, end: datetime) -> AsyncIterable[History]:
    """Fetch your reporting history."""

  @SDK.method
  async def history_sync(self, start: datetime, end: datetime) -> History:
    """Fetch your reporting history without streaming."""
    flows: list[Flow] = []
    events: list[Event] = []
    async for page in self.history(start, end):
      flows.extend(page.flows)
      events.extend(page.events)
    return History.History(flows=flows, events=events)