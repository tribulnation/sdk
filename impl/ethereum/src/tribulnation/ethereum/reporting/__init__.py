from .snapshots import Snapshots
from . import history
from .etherscan import EtherscanReport
from .alchemy import AlchemyReport

def ethereum(address: str, *, rpc_url: str | None = None):
  import os
  from tribulnation.ethereum.reporting import EtherscanReport
  from ethereum import PUBLIC_NODE_URLS
  rpc_url = rpc_url or os.environ.get('ETHEREUM_RPC_URL') or PUBLIC_NODE_URLS['ethereum']
  return EtherscanReport.new_at(rpc_url=rpc_url, chain_id=1, address=address)

def arbitrum(address: str, *, rpc_url: str | None = None):
  import os
  from tribulnation.ethereum.reporting import EtherscanReport
  from ethereum import PUBLIC_NODE_URLS
  rpc_url = rpc_url or os.environ.get('ARBITRUM_RPC_URL') or PUBLIC_NODE_URLS['arbitrum']
  return EtherscanReport.new_at(rpc_url=rpc_url, chain_id=42161, address=address)

def polygon(address: str, *, rpc_url: str | None = None):
  import os
  from tribulnation.ethereum.reporting import EtherscanReport
  from ethereum import PUBLIC_NODE_URLS
  rpc_url = rpc_url or os.environ.get('POLYGON_RPC_URL') or PUBLIC_NODE_URLS['polygon']
  return EtherscanReport.new_at(rpc_url=rpc_url, chain_id=137, address=address, poa_middleware=True)

def bnb(address: str, *, rpc_url: str | None = None):
  from tribulnation.ethereum.reporting import AlchemyReport
  from alchemy import BNB_ALCHEMY_URL
  return AlchemyReport.new(
    address=address, alchemy_url=BNB_ALCHEMY_URL,
    rpc_url=rpc_url, chain_id=56, poa_middleware=True
  )

def base(address: str, *, rpc_url: str | None = None):
  from tribulnation.ethereum.reporting import AlchemyReport
  from alchemy import BASE_ALCHEMY_URL
  return AlchemyReport.new(
    address=address, alchemy_url=BASE_ALCHEMY_URL,
    rpc_url=rpc_url, chain_id=8453, poa_middleware=False
  )

def avalanche(address: str, *, rpc_url: str | None = None):
  from tribulnation.ethereum.reporting import AlchemyReport
  from alchemy import AVAX_ALCHEMY_URL
  return AlchemyReport.new(
    address=address, alchemy_url=AVAX_ALCHEMY_URL,
    rpc_url=rpc_url, chain_id=43114, poa_middleware=True
  )

def optimism(address: str, *, rpc_url: str | None = None):
  from tribulnation.ethereum.reporting import AlchemyReport
  from alchemy import OPTIMISM_ALCHEMY_URL
  return AlchemyReport.new(
    address=address, alchemy_url=OPTIMISM_ALCHEMY_URL,
    rpc_url=rpc_url, chain_id=10, poa_middleware=True
  )
