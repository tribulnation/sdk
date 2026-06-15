from typing_extensions import Sequence, TypeVar, Callable, Awaitable
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime

from web3 import Web3
from moralis import Moralis
from moralis.core import Chain

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import Snapshots, Record, Snapshot, source_id
from tribulnation.ethereum.core import moralis as moralis_core
from ..config import NATIVE_ASSET

T = TypeVar('T')

NATIVE_DECIMALS = 18

@dataclass
class MoralisSnapshots(Snapshots):
  address: str
  chain: Chain
  moralis: Moralis = field(default_factory=Moralis.new)
  ignore_zero_value: bool = True

  @SDK.method
  @moralis_core.wrap_exceptions
  async def call_moralis(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Moralis under the SDK exception wrapper."""
    return await fn()

  async def moralis_token_balances(self):
    paging = self.moralis.evm.wallet.token_balances_paged(
      self.address,
      chain=self.chain,
      exclude_spam=True,
    )
    state = paging.init
    while state is not None:
      chunk, state = await self.call_moralis(lambda: paging.next(state)) # type: ignore
      for token in chunk:
        yield token

  async def snapshots(self, assets: Sequence[str] | None = None) -> Record:
    balances: dict[str, Decimal] = {}
    async for token in self.moralis_token_balances():
      address = token['token_address']
      asset = NATIVE_ASSET if token.get('native_token') else Web3.to_checksum_address(address)
      balance = token.get('balance_formatted')
      if balance is None:
        decimals = token.get('decimals') or NATIVE_DECIMALS
        qty = Decimal(token['balance']) * (Decimal(10) ** -decimals)
      else:
        qty = Decimal(balance)
      if not self.ignore_zero_value or qty > 0:
        balances[asset] = qty
    return Record(
      snapshots=[Snapshot(time=datetime.now().astimezone(), balances=balances)],
      provenance={'source': 'api', 'service': 'moralis', 'id': source_id('moralis')},
    )
