from typing_extensions import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import asyncio

from web3 import Web3
from web3.exceptions import ContractLogicError, BadFunctionCallOutput

from trading_sdk import ApiError, SDK
from trading_sdk.reporting import Snapshots as _Snapshots, Snapshot

from ethereum_sdk.core import rpc, etherscan

@dataclass
class Snapshots(rpc.Mixin, etherscan.Mixin, _Snapshots):
  address: str
  ignore_bad_contracts: bool = field(kw_only=True)
  ignore_zero_value: bool = field(kw_only=True)
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
  ):
    from etherscan import Etherscan
    from ethereum import NodeRpc
    etherscan = Etherscan.new(api_key=etherscan_api_key, validate=validate, rate_limit=etherscan_rate_limit)
    node = NodeRpc.at(rpc_url)
    return cls(
      node=node,
      etherscan=etherscan,
      chain_id=chain_id,
      address=address,
      ignore_bad_contracts=ignore_bad_contracts,
      ignore_zero_value=ignore_zero_value,
    )

  @etherscan.wrap_exceptions
  async def call(self, fn):
    return await fn()

  @SDK.method
  async def _list_assets(self):
    paging = self.etherscan.account.token_transactions_paged(self.address, self.chain_id)
    contracts = set[str]()
    state = paging.init
    while state is not None:
      chunk, state = await self.call(lambda: paging.next(state))
      contracts.update(tx['contractAddress'] for tx in chunk)
    return contracts

  @rpc.wrap_exceptions
  async def snapshots(self, assets: Sequence[str] = []) -> list[Snapshot]:
    eth_balance = Decimal(await self.node.eth_balance(self.address))
    time = datetime.now(timezone.utc)
    snapshots: list[Snapshot] = [Snapshot(asset=self.native_asset_id, qty=eth_balance, time=time, kind='currency')]
    contracts = assets or await self._list_assets()
    contracts = [Web3.to_checksum_address(contract) for contract in contracts]
    for contract in contracts:
      try:
        balance = await self.node.token(contract).balance(self.address)
      except (ContractLogicError, BadFunctionCallOutput) as e:
        if self.ignore_bad_contracts:
          continue
        else:
          raise ApiError(f'Contract {contract} raised a logic error', *e.args) from e
      if not self.ignore_zero_value or balance > 0:
        time = datetime.now().astimezone()
        snapshots.append(Snapshot(asset=contract, qty=balance, time=time, kind='currency'))

    return snapshots