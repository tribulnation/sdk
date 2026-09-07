from typed_moralis.schemas import WalletEvmChain
from tribulnation.ethereum.core import Network

MORALIS_CHAINS: dict[Network, WalletEvmChain] = {
  'ethereum': 'eth',
  'arbitrum': 'arbitrum',
  'polygon': 'polygon',
  'bnb-chain': 'bsc',
  'base': 'base',
  'avalanche': 'avalanche',
  'optimism': 'optimism',
}
