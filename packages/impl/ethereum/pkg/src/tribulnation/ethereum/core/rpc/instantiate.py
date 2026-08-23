from typing_extensions import Literal
import os
from ethereum import NodeRpc, Network, PUBLIC_NODE_URLS, ALCHEMY_NODE_URLS
from tribulnation.ethereum.core import POA_NETWORKS, RPC_ENV_VARS

def new(network: Network, rpc_url: str | None = None, preferred: Literal['public', 'alchemy'] = 'public'):
  poa = network in POA_NETWORKS
  if rpc_url is None:
    rpc_url = os.environ.get(RPC_ENV_VARS[network])
  if rpc_url is None:
    if preferred == 'alchemy' and (api_key := os.environ.get('ALCHEMY_API_KEY')) is not None:
      rpc_url = ALCHEMY_NODE_URLS[network].format(API_KEY=api_key)
    else:
      rpc_url = PUBLIC_NODE_URLS[network]
  return NodeRpc.at(rpc_url, poa_middleware=poa), rpc_url