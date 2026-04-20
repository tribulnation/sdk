from dataclasses import dataclass

from trading_sdk.reporting import Report as _Report
from ethereum_sdk.reporting.snapshots import Snapshots
from ethereum_sdk.reporting.history import AlchemyHistory
from etherscan import Etherscan
from alchemy.api.transfers import Transfers
from ethereum import NodeRpc

@dataclass
class AlchemyReport(_Report, Snapshots, AlchemyHistory):
  @classmethod
  def new(
    cls, address: str, *,
    ignore_bad_contracts: bool = True, ignore_zero_value: bool = False,
    alchemy_url: str, rpc_url: str | None = None, chain_id: int,
    alchemy_api_key: str | None = None, poa_middleware: bool = False,
    etherscan_api_key: str | None = None, etherscan_rate_limit: int | None = None,
    validate: bool = True, include_internal_transfers: bool = False,
  ):
    if alchemy_api_key is None:
      import os
      alchemy_api_key = os.environ['ALCHEMY_API_KEY']
    if rpc_url is None:
      rpc_url = alchemy_url + '/' + alchemy_api_key
    node = NodeRpc.at(rpc_url, poa_middleware=poa_middleware)
    etherscan = Etherscan.new(etherscan_api_key, rate_limit=etherscan_rate_limit, validate=validate)
    transfers = Transfers.new(alchemy_url, api_key=alchemy_api_key)
    return cls(
      address,
      ignore_bad_contracts=ignore_bad_contracts,
      ignore_zero_value=ignore_zero_value,
      etherscan=etherscan,
      chain_id=chain_id,
      node=node,
      alchemy_transfers=transfers,
      include_internal_transfers=include_internal_transfers,
    )