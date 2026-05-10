from typing_extensions import Collection
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import asyncio

from web3 import Web3
from web3.exceptions import ContractLogicError, BadFunctionCallOutput

from tribulnation.sdk import ApiError, SDK
from tribulnation.sdk.reporting import Balance, Record, Snapshots as _Snapshots, Snapshot

from tribulnation.ethereum.core import rpc, etherscan

@dataclass
class Snapshots(rpc.Mixin, etherscan.Mixin, _Snapshots):
  address: str
  ignore_bad_contracts: bool = field(default=True, kw_only=True)
  ignore_zero_value: bool = field(default=True, kw_only=True)
  native_asset_id: str = field(default='native', kw_only=True)

  async def __aenter__(self):
    await asyncio.gather(
      self.node.__aenter__(),
      self.etherscan.__aenter__(),
    )
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(
      self.node.__aexit__(exc_type, exc_value, traceback),
      self.etherscan.__aexit__(exc_type, exc_value, traceback),
    )

  @classmethod
  def new_at(
    cls, rpc_url: str, *, address: str, chain_id: int,
    validate: bool = True, etherscan_api_key: str | None = None,
    etherscan_rate_limit: int | None = None,
    ignore_bad_contracts: bool = True, ignore_zero_value: bool = True,
    poa_middleware: bool = False,
  ):
    from etherscan import Etherscan
    from ethereum import NodeRpc
    etherscan = Etherscan.new(api_key=etherscan_api_key, validate=validate, rate_limit=etherscan_rate_limit)
    node = NodeRpc.at(rpc_url, poa_middleware=poa_middleware)
    return cls(
      node=node,
      etherscan=etherscan,
      chain_id=chain_id,
      address=address,
      ignore_bad_contracts=ignore_bad_contracts,
      ignore_zero_value=ignore_zero_value,
    )

  @SDK.method
  @etherscan.wrap_exceptions
  async def call_etherscan(self, fn):
    return await fn()

  @SDK.method
  async def _list_assets(self):
    paging = self.etherscan.account.token_transactions_paged(self.address, self.chain_id)
    contracts = set[str]()
    state = paging.init
    while state is not None:
      async def next():
        nonlocal state
        return await paging.next(state)
      chunk, next_state = await self.call_etherscan(next) # type: ignore
      state = next_state
      contracts.update(tx['contractAddress'] for tx in chunk)
    return contracts

  @SDK.method
  @rpc.wrap_exceptions
  async def eth_balance(self) -> Decimal:
    return Decimal(await self.node.eth_balance(self.address))

  @SDK.method
  @rpc.wrap_exceptions
  async def token_balance(self, contract: str) -> Decimal | None:
    try:
      return Decimal(await self.node.token(contract).balance(self.address))
    except (ContractLogicError, BadFunctionCallOutput) as e:
      if not self.ignore_bad_contracts:
        raise ApiError(f'Contract {contract} raised a logic error', *e.args) from e
    

  @rpc.wrap_exceptions
  async def snapshots(self, assets: Collection[str] | None = None) -> Record:
    """Snapshot native balance and selected/discovered ERC20 balances."""
    eth_balance = await self.eth_balance()
    time = datetime.now(timezone.utc)
    balances: dict[str, Balance] = {
      self.native_asset_id: Balance(qty=eth_balance, kind='currency')
    }
    contracts = assets if assets is not None else await self._list_assets()
    contracts = [Web3.to_checksum_address(contract) for contract in contracts if contract != self.native_asset_id]
    for contract in contracts:
      balance = await self.token_balance(contract)
      if balance is not None and (not self.ignore_zero_value or balance > 0):
        balances[contract] = Balance(qty=balance, kind='currency')

    return Record(
      snapshots=[Snapshot(time=time, balances=balances)],
      provenance={'source': 'api', 'service': 'node_rpc'},
    )
