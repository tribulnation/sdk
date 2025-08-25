from typing_extensions import Literal, TypeGuard

Network = Literal[
  'BSC',
  'ETH',
  'POL',
  'TRX',
  'ARB',
  'BASE',
  'AVAX',
  'SOL',
  'FTM',
  'OP',
  'TON',
  'SONIC',
  'XTZ',
  'CORE',
  'CELO',
  'NEAR',
  'MNT',
  'UNI',
  'APTOS',
  'SUI',
]

NETWORK_NAMES: dict[Network, str] = {
  'BSC': 'Binance Smart Chain',
  'ETH': 'Ethereum',
  'POL': 'Polygon',
  'TRX': 'Tron',
  'ARB': 'Arbitrum',
  'BASE': 'Base',
  'AVAX': 'Avalanche',
  'SOL': 'Solana',
  'FTM': 'Fantom',
  'OP': 'Optimism',
  'TON': 'The Open Network',
  'SONIC': 'Sonic',
  'XTZ': 'Tezos',
  'CORE': 'Core',
  'CELO': 'Celo',
  'NEAR': 'Near',
  'MNT': 'Mantle',
  'UNI': 'Unichain',
  'APTOS': 'Aptos',
  'SUI': 'Sui',
}

def is_network(s: str) -> TypeGuard[Network]:
  return s in NETWORK_NAMES