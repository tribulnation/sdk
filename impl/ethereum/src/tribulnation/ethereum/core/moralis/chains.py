from moralis.core import Chain
from tribulnation.ethereum.core import Network

MORALIS_CHAINS: dict[Network, Chain] = {
  'ethereum': 'eth',
  'arbitrum': 'arbitrum',
  'polygon': 'polygon',
  'bnb-chain': 'bsc',
  'base': 'base',
  'avalanche': 'avalanche',
  'optimism': 'optimism',
}