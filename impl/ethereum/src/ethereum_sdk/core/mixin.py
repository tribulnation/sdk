from dataclasses import dataclass
from web3 import Web3
from .etherscan import Etherscan, EtherscanMixin, ETHERSCAN_API_URL
from .rpc import NodeRpc, NodeRpcMixin

@dataclass(kw_only=True)
class Mixin(EtherscanMixin, NodeRpcMixin):
  @classmethod
  def new_at(
    cls, rpc_url: str, *, address: str, chain_id: int,
    ignore_bad_contracts: bool = True, ignore_zero_value: bool = True,
    etherscan_api_key: str | None = None,
    etherscan_base_url: str = ETHERSCAN_API_URL,
    validate: bool = True,
  ):
    address = Web3.to_checksum_address(address)
    etherscan = Etherscan.new(api_key=etherscan_api_key, base_url=etherscan_base_url, validate=validate)
    node = NodeRpc.at(rpc_url)
    return cls(
      etherscan=etherscan, node=node,
      address=address, chain_id=chain_id,
      ignore_zero_value=ignore_zero_value,
      ignore_bad_contracts=ignore_bad_contracts,
    )