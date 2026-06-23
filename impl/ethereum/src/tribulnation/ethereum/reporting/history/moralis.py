from typing_extensions import TypeVar, Callable, Awaitable
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
import asyncio

from moralis import Moralis
from moralis.core import Chain
from moralis.evm.wallet.history import (
  WalletHistoryTransaction,
  NativeTransfer,
  TokenTransfer,
  NftTransfer,
)

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import History, Record, EvmTx, Fee, source_id
from tribulnation.ethereum.core import Network, moralis as moralis_core, same_address
from tribulnation.ethereum.reporting.history.mixin import HistoryMixin

T = TypeVar('T')

def native_value(transfer: NativeTransfer) -> Decimal:
  """Return a native transfer value in display units."""
  if (formatted := transfer.get('value_formatted')) is not None:
    return Decimal(formatted)
  return Decimal(transfer['value']) * (Decimal(10) ** -18)

def token_value(transfer: TokenTransfer) -> Decimal:
  """Return an ERC20 transfer value in display units."""
  if (value := transfer.get('value_decimal')) is not None:
    return Decimal(value)
  decimals = int(transfer.get('token_decimals') or '0')
  return Decimal(transfer['value']) * (Decimal(10) ** -decimals)

@dataclass(frozen=True, kw_only=True)
class MoralisHistory(HistoryMixin, History):
  address: str
  chain: Chain
  moralis: Moralis = field(default_factory=Moralis.new)
  batch_size: int = 4

  @classmethod
  def new(cls, address: str, *, network: Network, rpc_url: str | None = None, api_key: str | None = None):
    from moralis import Moralis
    from tribulnation.ethereum.core import rpc, MORALIS_CHAINS
    node, rpc_url = rpc.new(network, rpc_url, preferred='alchemy')
    moralis = Moralis.new(api_key)
    return cls(address=address, chain=MORALIS_CHAINS[network], node=node, rpc_url=rpc_url, moralis=moralis)

  async def __aenter__(self):
    await asyncio.gather(
      super().__aenter__(),
      self.moralis.__aenter__(),
    )
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(
      super().__aexit__(exc_type, exc_value, traceback),
      self.moralis.__aexit__(exc_type, exc_value, traceback),
    )

  @SDK.method
  @moralis_core.wrap_exceptions
  async def call_moralis(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Moralis under the SDK exception wrapper."""
    return await fn()

  async def wallet_history(self, start: datetime | None = None, end: datetime | None = None):
    paging = self.moralis.evm.wallet.history_paged(
      self.address,
      chain=self.chain,
      from_date=start and start.isoformat() or None,
      to_date=end and end.isoformat() or None,
      include_internal_transactions=True,
    )
    state = paging.init
    while state is not None:
      chunk, state = await self.call_moralis(lambda: paging.next(state)) # type: ignore
      yield chunk

  def parse_moralis_fee(self, tx: WalletHistoryTransaction) -> Fee | None:
    if (fee := tx.get('transaction_fee')) and same_address(tx['from_address'], self.address):
      return Fee(amount=Decimal(fee), asset='native')

  def parse_moralis_native_transfer(self, transfer: NativeTransfer) -> EvmTx.NativeTransfer | None:
    value = native_value(transfer)
    if same_address(transfer['from_address'], self.address):
      amount = -value
      counterparty = transfer['to_address']
    elif same_address(transfer['to_address'], self.address):
      amount = value
      counterparty = transfer['from_address']
    else:
      return None
    
    return EvmTx.NativeTransfer(
      change=amount,
      counterparty=counterparty,
      internal=bool(transfer.get('internal_transaction'))
    )

  def parse_moralis_native_transfers(self, tx: WalletHistoryTransaction):
    for transfer in tx.get('native_transfers', []):
      if (transfer := self.parse_moralis_native_transfer(transfer)) is not None:
        yield transfer

  def parse_nft_transfer(self, transfer: NftTransfer) -> EvmTx.NftTransfer | None:
    if (
      (from_ := transfer.get('from_address')) is None
      or (to := transfer.get('to_address')) is None
      or (token_id := transfer.get('token_id')) is None
      or (contract_address := transfer.get('token_address')) is None
    ):
      return
    if same_address(from_, self.address):
      sign = -1
      counterparty = to
    elif same_address(to, self.address):
      sign = 1
      counterparty = from_
    else:
      return None

    return EvmTx.NftTransfer(
      contract_address=contract_address,
      token_id=token_id,
      change=Decimal(sign),
      counterparty=counterparty,
    )

  def parse_nft_transfers(self, tx: WalletHistoryTransaction):
    for transfer in tx.get('nft_transfers', []):
      if (transfer := self.parse_nft_transfer(transfer)) is not None:
        yield transfer


  def parse_token_transfer(self, transfer: TokenTransfer) -> EvmTx.ERC20Transfer | None:
    if not (from_ := transfer.get('from_address')) or not (to := transfer.get('to_address')):
      return
    value = token_value(transfer)
    if same_address(from_, self.address):
      amount = -value
      counterparty = to
    elif same_address(to, self.address):
      amount = value
      counterparty = from_
    else:
      return None

    return EvmTx.ERC20Transfer(
      asset=transfer['address'],
      change=amount,
      counterparty=counterparty,
    )

  def parse_token_transfers(self, tx: WalletHistoryTransaction):
    for transfer in tx.get('erc20_transfers', []):
      if (transfer := self.parse_token_transfer(transfer)) is not None:
        yield transfer


  async def parse_moralis_tx(self, wallet_tx: WalletHistoryTransaction) -> EvmTx | None:
    hash = wallet_tx['hash']
    time = wallet_tx.get('block_timestamp')
    tx, receipt = await self.get_tx_data(hash)
    if time:
      transfers = (
        list(self.parse_moralis_native_transfers(wallet_tx))
        + list(self.parse_token_transfers(wallet_tx))
        + list(self.parse_nft_transfers(wallet_tx))
      )
      fee_node = self.parse_fee(tx, receipt)
      fee_moralis = self.parse_moralis_fee(wallet_tx)
      if (fee_node is None) != (fee_moralis is None):
        raise ValueError(f'Fee mismatch: {fee_node} != {fee_moralis}')
      elif fee_node and fee_moralis and fee_node.amount != fee_moralis.amount:
        raise ValueError(f'Fee mismatch: {fee_node.amount} != {fee_moralis.amount}')
      return EvmTx(
        id=hash, tx_id=hash,
        time=datetime.fromisoformat(time),
        fee=self.parse_fee(tx, receipt),
        transfers=transfers,
        execution=await self.parse_execution(tx, receipt),
      )

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    id = source_id('moralis')
    semaphore = asyncio.Semaphore(self.batch_size)
    async def parse_limited(wallet_tx: WalletHistoryTransaction):
      async with semaphore:
        return await self.parse_moralis_tx(wallet_tx)
        
    async for chunk in self.wallet_history(start=start, end=end):
      for tx in chunk:
        if evm_tx := await parse_limited(tx):
          yield Record(observations=[evm_tx], provenance={'source': 'api', 'service': 'etherscan', 'id': id})