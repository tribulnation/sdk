from decimal import Decimal
from typing_extensions import Sequence, TypeVar, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime

from web3 import Web3
from alchemy import Alchemy

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import Snapshots, Record, Balance, Snapshot
from tribulnation.ethereum.core import alchemy as alchemy_core
from ..config import NATIVE_ASSET
from ..util import source_id

T = TypeVar('T')

def hex_balance(value: str) -> int:
  """Parse an Alchemy hex-encoded balance."""
  return int(value, 16) if value.startswith('0x') else int(value)

NATIVE_DECIMALS = 18

def token_qty(value: str, decimals: int | None) -> Decimal:
  """Convert a raw integer token balance into display units."""
  return Decimal(hex_balance(value)) * (Decimal(10) ** -(decimals or NATIVE_DECIMALS))

@dataclass(frozen=True, kw_only=True)
class AlchemySnapshots(Snapshots):
  address: str
  alchemy: Alchemy = field(default_factory=Alchemy.new)
  network: str
  ignore_zero_value: bool = True

  async def __aenter__(self):
    await self.alchemy.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.alchemy.__aexit__(exc_type, exc_value, traceback)

  @SDK.method
  @alchemy_core.wrap_exceptions
  async def call_alchemy(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Alchemy under the SDK exception wrapper."""
    return await fn()

  async def alchemy_portfolio_tokens(self):
    paging = self.alchemy.portfolio.tokens.paged({
      'addresses': [{
        'address': self.address,
        'networks': [self.network],
      }],
      'withMetadata': True,
      'withPrices': True,
      'includeNativeTokens': True,
      'includeErc20Tokens': True,
    })
    state = paging.init
    while state is not None:
      chunk, state = await self.call_alchemy(lambda: paging.next(state)) # type: ignore
      for token in chunk:
        yield token

  async def snapshots(self, assets: Sequence[str] | None = None) -> Record:
    balances: dict[str, Balance] = {}
    tokens = [token async for token in self.alchemy_portfolio_tokens()]
    for token in tokens:
      address = token.get('tokenAddress')
      metadata = token.get('tokenMetadata') or {}
      asset = NATIVE_ASSET if address is None else Web3.to_checksum_address(address)
      qty = token_qty(token['tokenBalance'], metadata.get('decimals'))
      if qty > 0 or not self.ignore_zero_value:
        balances[asset] = Balance(qty=qty, kind='currency')
    return Record(
      snapshots=[Snapshot(time=datetime.now().astimezone(), balances=balances)],
      provenance={'source': 'api', 'service': 'alchemy', 'id': source_id('alchemy')},
    )