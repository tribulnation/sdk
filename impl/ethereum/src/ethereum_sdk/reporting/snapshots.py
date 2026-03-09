from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from web3 import Web3
from web3.exceptions import ContractLogicError, BadFunctionCallOutput

from trading_sdk import ApiError, SDK
from trading_sdk.reporting import Snapshots as _Snapshots, Snapshot

from ethereum_sdk.core import Mixin

@dataclass
class Snapshots(_Snapshots, Mixin):

  @SDK.method
  async def _list_assets(self):
    txs = await self.etherscan.token_transactions_paged_sync(self.address, self.chain_id)
    return set(tx['contractAddress'] for tx in txs)

  async def snapshots(self, assets: Sequence[str] = []) -> list[Snapshot]:
    eth_balance = Decimal(await self.node.eth_balance(self.address))
    time = datetime.now(timezone.utc)
    snapshots: list[Snapshot] = [Snapshot(asset='ETH', qty=eth_balance, time=time, kind='currency')]
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
      time = datetime.now().astimezone()
      snapshots.append(Snapshot(asset=contract, qty=balance, time=time, kind='currency'))

    return snapshots