from typing_extensions import Callable, Awaitable, TypeVar
from collections import defaultdict
from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal

from moralis import Moralis
from moralis.evm.wallet.history import NativeTransfer, WalletHistoryTransaction
from moralis.evm.wallet.token_transfers import TokenTransfer
from typing_extensions import AsyncIterable
from web3 import Web3

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import EvmTx, Fee, Record
from tribulnation.ethereum.core import same_address, moralis as moralis_core
from ..constants import MORALIS_CHAINS
from ..config import EvmNetwork

T = TypeVar('T')

def parse_time(value: str | None) -> datetime | None:
  """Parse a Moralis ISO timestamp."""
  if value is None:
    return None
  return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone()

def decimal_value(value: str | int | float | None) -> Decimal:
  """Parse a Moralis numeric field."""
  return Decimal(str(value or '0'))

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


@dataclass(frozen=True)
class MoralisHistory(SDK):
  """Moralis-backed EVM history source."""
  address: str
  network: EvmNetwork
  moralis: Moralis | None

  def require_moralis(self) -> Moralis:
    """Return the configured Moralis client or raise a concrete configuration error."""
    if self.moralis is None:
      raise ValueError('EVM Moralis history requires a Moralis provider.')
    return self.moralis

  @SDK.method
  @moralis_core.wrap_exceptions
  async def call_moralis(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Moralis under the SDK exception wrapper."""
    return await fn()

  async def moralis_wallet_history(
    self, start: datetime | None = None, end: datetime | None = None,
  ) -> list[WalletHistoryTransaction]:
    """Fetch decoded Moralis wallet history."""
    paging = self.require_moralis().evm.wallet.history_paged(
      self.address,
      chain=MORALIS_CHAINS[self.network],
      from_date=start.isoformat() if start is not None else None,
      to_date=end.isoformat() if end is not None else None,
      include_internal_transactions=True,
      limit=25,
    )
    out: list[WalletHistoryTransaction] = []
    state = paging.init
    while state is not None:
      chunk, state = await self.call_moralis(lambda: paging.next(state)) # type: ignore
      out.extend(chunk)
    return out

  async def moralis_token_transfers(
    self, start: datetime | None = None, end: datetime | None = None,
  ) -> list[TokenTransfer]:
    """Fetch Moralis ERC20 transfer history."""
    paging = self.require_moralis().evm.wallet.token_transfers_paged(
      self.address,
      chain=MORALIS_CHAINS[self.network],
      from_date=start.isoformat() if start is not None else None,
      to_date=end.isoformat() if end is not None else None,
      limit=25,
    )
    out: list[TokenTransfer] = []
    state = paging.init
    while state is not None:
      chunk, state = await self.call_moralis(lambda: paging.next(state)) # type: ignore
      out.extend(chunk)
    return out

  def parse_moralis_fee(self, tx: WalletHistoryTransaction) -> Fee | None:
    """Parse a transaction fee paid by this wallet."""
    if not same_address(tx['from_address'], self.address):
      return None
    amount = decimal_value(tx.get('transaction_fee'))
    if amount == 0:
      return None
    return Fee(asset='native', amount=amount)

  def parse_moralis_execution(self, tx: WalletHistoryTransaction) -> EvmTx.Execution | None:
    """Parse execution metadata from a decoded Moralis transaction."""
    to_address = tx.get('to_address')
    method = tx.get('method_label')
    if to_address is None or method is None:
      return None
    return EvmTx.Execution(
      contract_address=Web3.to_checksum_address(to_address),
      input=None,
      method_name=method,
    )

  def parse_native_transfer(self, transfer: NativeTransfer) -> EvmTx.NativeTransfer | None:
    """Parse a Moralis native transfer into an SDK EVM transfer."""
    if same_address(transfer['to_address'], self.address):
      amount = native_value(transfer)
      counterparty = transfer['from_address']
    elif same_address(transfer['from_address'], self.address):
      amount = -native_value(transfer)
      counterparty = transfer['to_address']
    else:
      return None
    return EvmTx.NativeTransfer(
      change=amount,
      counterparty=counterparty,
      internal=transfer.get('internal_transaction', False),
    )

  def parse_token_transfer(self, transfer: TokenTransfer) -> EvmTx.ERC20Transfer | None:
    """Parse a Moralis ERC20 transfer into an SDK EVM transfer."""
    to_address = transfer.get('to_address')
    from_address = transfer.get('from_address')
    if to_address is not None and same_address(to_address, self.address):
      amount = token_value(transfer)
      counterparty = from_address
    elif from_address is not None and same_address(from_address, self.address):
      amount = -token_value(transfer)
      counterparty = to_address
    else:
      return None
    return EvmTx.ERC20Transfer(
      asset=Web3.to_checksum_address(transfer['address']),
      change=amount,
      counterparty=counterparty,
    )

  def parse_moralis_tx(
    self,
    hash: str,
    *,
    wallet_txs: list[WalletHistoryTransaction],
    token_transfers: list[TokenTransfer],
  ) -> EvmTx | None:
    """Build an SDK EVM transaction from Moralis wallet and transfer rows."""
    wallet_tx = wallet_txs[0] if wallet_txs else None
    transfers: list[EvmTx.NativeTransfer | EvmTx.ERC20Transfer] = []
    if wallet_tx is not None:
      transfers.extend([
        transfer for raw in wallet_tx.get('native_transfers', [])
        if (transfer := self.parse_native_transfer(raw)) is not None
      ])
    transfers.extend([
      transfer for raw in token_transfers
      if (transfer := self.parse_token_transfer(raw)) is not None
    ])
    if wallet_tx is None and not token_transfers:
      return None
    time = parse_time(
      wallet_tx.get('block_timestamp')
      if wallet_tx is not None
      else token_transfers[0].get('block_timestamp')
    )
    fee = self.parse_moralis_fee(wallet_tx) if wallet_tx is not None else None
    execution = self.parse_moralis_execution(wallet_tx) if wallet_tx is not None else None
    if fee is None and execution is None and not transfers:
      return None
    return EvmTx(
      id=hash,
      tx_id=hash,
      time=time,
      fee=fee,
      execution=execution,
      transfers=transfers,
    )

  async def moralis_history(
    self, start: datetime | None = None, end: datetime | None = None,
  ) -> AsyncIterable[Record]:
    """Fetch EVM history from Moralis wallet history and ERC20 transfer endpoints."""
    start = start.astimezone() if start is not None else None
    end = end.astimezone() if end is not None else None
    wallet_rows = await self.moralis_wallet_history(start=start, end=end)
    token_rows = await self.moralis_token_transfers(start=start, end=end)
    wallet_by_hash: dict[str, list[WalletHistoryTransaction]] = defaultdict(list)
    token_by_hash: dict[str, list[TokenTransfer]] = defaultdict(list)
    for row in wallet_rows:
      wallet_by_hash[row['hash']].append(row)
    for row in token_rows:
      if (hash := row.get('transaction_hash')) is not None:
        token_by_hash[hash].append(row)
    hashes = set(wallet_by_hash) | set(token_by_hash)
    for hash in hashes:
      tx = self.parse_moralis_tx(
        hash,
        wallet_txs=wallet_by_hash.get(hash, []),
        token_transfers=token_by_hash.get(hash, []),
      )
      if tx is not None:
        yield Record(observations=[tx], provenance={'source': 'api', 'service': 'moralis'})
