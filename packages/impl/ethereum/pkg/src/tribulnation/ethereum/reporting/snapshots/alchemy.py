"""Alchemy-backed EVM balances: one paged Portfolio call enumerates the native and every
ERC-20 balance, with the metadata needed to scale each one.
"""

from decimal import Decimal
from typing_extensions import (
  AsyncContextManager,
  Collection,
  Iterable,
  TypeVar,
  Callable,
  Awaitable,
)
from dataclasses import dataclass, field

from web3 import Web3
from typed_alchemy import Alchemy
from typed_alchemy.portfolio.tokens import Token

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import (
  Balances,
  Snapshot,
  SnapshotRecord,
  Snapshots,
  SubaccountSnapshot,
  source_id,
)
from tribulnation.ethereum.core import alchemy as alchemy_core
from ..config import NATIVE_ASSET

T = TypeVar('T')

NATIVE_DECIMALS = 18


def raw_balance(token: Token) -> int:
  """Parse Alchemy's `tokenBalance`, a 0x-prefixed hex integer."""
  value = token['tokenBalance']
  return int(value, 16) if value.startswith('0x') else int(value)


def token_amount(token: Token) -> Decimal:
  """Convert one portfolio row's raw balance into display units.

  The native row carries no metadata, so its decimals are `None` and 18 is the right
  default. A token that declares `0` decimals keeps its raw integer.
  """
  metadata = token.get('tokenMetadata')
  decimals = None if metadata is None else metadata.get('decimals')
  if decimals is None:
    decimals = NATIVE_DECIMALS
  return Decimal(raw_balance(token)) * (Decimal(10) ** -decimals)


@dataclass(frozen=True, kw_only=True)
class AlchemySnapshots(Snapshots):
  """Alchemy-backed EVM balances source."""

  address: str
  alchemy: Alchemy = field(default_factory=Alchemy.new)
  network: str
  ignore_zero_value: bool = True

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.alchemy

  @SDK.method
  @alchemy_core.wrap_exceptions
  async def call_alchemy(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Alchemy under the SDK exception wrapper."""
    return await fn()

  async def alchemy_portfolio_tokens(self) -> list[Token]:
    """Fetch every fungible balance Alchemy reports for the address on the network."""
    paging = self.alchemy.portfolio.tokens_paged(
      [{'address': self.address, 'networks': [self.network]}],
      with_metadata=True,
      with_prices=True,
      include_native_tokens=True,
      include_erc20tokens=True,
    )
    return list(await paging.via(self.call_alchemy))

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    balances = Balances()
    for token in await self.alchemy_portfolio_tokens():
      contract = token['tokenAddress']
      asset = NATIVE_ASSET if contract is None else Web3.to_checksum_address(contract)
      qty = token_amount(token)
      if qty > 0 or not self.ignore_zero_value:
        balances[asset] = qty
    return SnapshotRecord(
      snapshot=Snapshot(
        subaccounts=[SubaccountSnapshot(balances=balances)],
      ),
      provenance={'source': 'api', 'service': 'alchemy', 'id': source_id('alchemy')},
    )
