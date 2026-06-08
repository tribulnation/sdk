from typing_extensions import Literal
from ethereum import Network

CHAIN_IDS: dict[Network, int] = {
  'ethereum': 1,
  'arbitrum': 42161,
  'polygon': 137,
  'bnb': 56,
  'base': 8453,
  'avalanche': 43114,
  'optimism': 10,
}

RPC_ENV_VARS: dict[Network, str] = {
  'ethereum': 'ETHEREUM_RPC_URL',
  'arbitrum': 'ARBITRUM_RPC_URL',
  'polygon': 'POLYGON_RPC_URL',
  'bnb': 'BNB_RPC_URL',
  'base': 'BASE_RPC_URL',
  'avalanche': 'AVALANCHE_RPC_URL',
  'optimism': 'OPTIMISM_RPC_URL',
}

POA_NETWORKS: set[Network] = {'bnb', 'avalanche', 'optimism', 'polygon'}