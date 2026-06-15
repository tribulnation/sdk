from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from web3 import Web3
from web3.exceptions import BadFunctionCallOutput, ContractLogicError
from ethereum import NodeRpc

from tribulnation.sdk import SDK, ApiError
from tribulnation.sdk.reporting import Snapshots, Record, Snapshot, source_id
from tribulnation.ethereum.core import rpc
from ..config import NATIVE_ASSET

@dataclass(frozen=True, kw_only=True)
class NodeSnapshots(Snapshots):
  address: str
  node: NodeRpc
  rpc_url: str
  ignore_bad_contracts: bool = True
  ignore_zero_value: bool = True
  batch_size: int = 32

  async def __aenter__(self):
    await self.node.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.node.__aexit__(exc_type, exc_value, traceback)

  @SDK.method
  @rpc.wrap_exceptions
  async def eth_balance(self) -> Decimal:
    """Fetch the native token balance from the configured node."""
    return Decimal(await self.node.eth_balance(self.address))

  @SDK.method
  @rpc.wrap_exceptions
  async def token_balance(self, contract: str) -> Decimal | None:
    """Fetch an ERC20 token balance from the configured node."""
    try:
      return Decimal(await self.node.token(contract).balance(self.address))
    except (ContractLogicError, BadFunctionCallOutput) as exc:
      if not self.ignore_bad_contracts:
        raise ApiError(f'Contract {contract} raised a logic error', *exc.args) from exc
      return None

  @rpc.wrap_exceptions
  async def snapshots(self, assets: Sequence[str] | None = None) -> Record:
    assets = assets or []
    time = datetime.now().astimezone()
    balances: dict[str, Decimal] = {
      NATIVE_ASSET: await self.eth_balance(),
    }

    semaphore = asyncio.Semaphore(self.batch_size)
    async def limited_token_balance(contract: str):
      async with semaphore:
        return await self.token_balance(contract), contract

    contracts = [
      Web3.to_checksum_address(contract)
      for contract in assets
      if contract != NATIVE_ASSET
    ]
    tasks = [limited_token_balance(contract) for contract in contracts]
    for task in asyncio.as_completed(tasks):
      balance, contract = await task
      if balance is not None and (not self.ignore_zero_value or balance > 0):
        balances[contract] = balance

    return Record(
      snapshots=[Snapshot(time=time, balances=balances)],
      provenance={'source': 'api', 'service': 'node_rpc', 'id': source_id('node_rpc')},
    )