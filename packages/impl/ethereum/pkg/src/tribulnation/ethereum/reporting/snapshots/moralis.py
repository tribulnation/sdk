"""Moralis-backed EVM balances: one paged call enumerates the native and every ERC-20
balance, each with its decimals and a pre-scaled amount.
"""

from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Collection,
  Iterable,
  TypeVar,
)
from dataclasses import dataclass, field
from decimal import Decimal

from web3 import Web3
from typed_moralis import Moralis
from typed_moralis.schemas import WalletEvmChain
from typed_moralis.evm.wallet.token_balances import TokenBalance

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import (
  Balances,
  Snapshot,
  SnapshotRecord,
  Snapshots,
  SubaccountSnapshot,
  source_id,
)
from tribulnation.ethereum.core import moralis as moralis_core
from ..config import NATIVE_ASSET

T = TypeVar('T')

NATIVE_DECIMALS = 18


def token_amount(token: TokenBalance) -> Decimal:
  """Convert one balance row into display units.

  `balance_formatted` is preferred when present. The fallback tests `decimals is None`,
  not truthiness: a token declaring `0` decimals keeps its raw integer.
  """
  formatted = token.get('balance_formatted')
  if formatted is not None:
    return Decimal(formatted)
  decimals = token.get('decimals')
  if decimals is None:
    decimals = NATIVE_DECIMALS
  return Decimal(token['balance']) * (Decimal(10) ** -decimals)


def asset_id(token: TokenBalance) -> str | None:
  """The SDK asset key for a balance row, or `None` when it cannot be identified."""
  if token.get('native_token'):
    return NATIVE_ASSET
  contract = token.get('token_address')
  return None if contract is None else Web3.to_checksum_address(contract)


@dataclass
class MoralisSnapshots(Snapshots):
  """Moralis-backed EVM balances source."""

  address: str
  chain: WalletEvmChain
  moralis: Moralis = field(default_factory=Moralis.new)
  ignore_zero_value: bool = True

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.moralis

  @SDK.method
  @moralis_core.wrap_exceptions
  async def call_moralis(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Moralis under the SDK exception wrapper."""
    return await fn()

  async def moralis_token_balances(self) -> list[TokenBalance]:
    """Fetch every balance Moralis reports for the address on the chain."""
    paging = self.moralis.evm.wallet.token_balances_paged(
      address=self.address, chain=self.chain, exclude_spam=True
    )
    return list(await paging.via(self.call_moralis))

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    balances = Balances()
    for token in await self.moralis_token_balances():
      asset = asset_id(token)
      if asset is None:
        continue
      qty = token_amount(token)
      if not self.ignore_zero_value or qty > 0:
        balances[asset] = qty
    return SnapshotRecord(
      snapshot=Snapshot(
        subaccounts=[SubaccountSnapshot(balances=balances)],
      ),
      provenance={'source': 'api', 'service': 'moralis', 'id': source_id('moralis')},
    )
