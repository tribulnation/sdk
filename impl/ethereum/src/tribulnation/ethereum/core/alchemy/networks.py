from ethereum import Network

ALCHEMY_NETWORKS: dict[Network, str] = {
  'ethereum': 'eth-mainnet',
  'arbitrum': 'arb-mainnet',
  'polygon': 'polygon-mainnet',
  'bnb-chain': 'bnb-mainnet',
  'base': 'base-mainnet',
  'avalanche': 'avax-mainnet',
  'optimism': 'opt-mainnet',
}