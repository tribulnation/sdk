"""Constants for EVM reporting source selection and network wiring."""

from moralis.core import Chain

from .config import EvmNetwork


DEFAULT_ASSETS_SOURCE = 'alchemy'
DEFAULT_SNAPSHOT_ASSETS_SOURCE = 'node'

DEFAULT_HISTORY_SOURCES: dict[EvmNetwork, str] = {
  'ethereum': 'etherscan',
  'arbitrum': 'etherscan',
  'polygon': 'etherscan',
  'bnb': 'moralis',
  'base': 'moralis',
  'avalanche': 'moralis',
  'optimism': 'moralis',
}

CHAIN_IDS: dict[EvmNetwork, int] = {
  'ethereum': 1,
  'arbitrum': 42161,
  'polygon': 137,
  'bnb': 56,
  'base': 8453,
  'avalanche': 43114,
  'optimism': 10,
}

RPC_ENV_VARS: dict[EvmNetwork, str] = {
  'ethereum': 'ETHEREUM_RPC_URL',
  'arbitrum': 'ARBITRUM_RPC_URL',
  'polygon': 'POLYGON_RPC_URL',
  'bnb': 'BNB_RPC_URL',
  'base': 'BASE_RPC_URL',
  'avalanche': 'AVALANCHE_RPC_URL',
  'optimism': 'OPTIMISM_RPC_URL',
}

ALCHEMY_NETWORKS: dict[EvmNetwork, str] = {
  'ethereum': 'eth-mainnet',
  'arbitrum': 'arb-mainnet',
  'polygon': 'polygon-mainnet',
  'bnb': 'bnb-mainnet',
  'base': 'base-mainnet',
  'avalanche': 'avax-mainnet',
  'optimism': 'opt-mainnet',
}

ALCHEMY_TRANSFER_NETWORKS: dict[EvmNetwork, str] = {
  'ethereum': 'ethereum',
  'arbitrum': 'arbitrum',
  'polygon': 'polygon',
  'bnb': 'bnb',
  'base': 'base',
  'avalanche': 'avalanche',
  'optimism': 'optimism',
}

MORALIS_CHAINS: dict[EvmNetwork, Chain] = {
  'ethereum': 'eth',
  'arbitrum': 'arbitrum',
  'polygon': 'polygon',
  'bnb': 'bsc',
  'base': 'base',
  'avalanche': 'avalanche',
  'optimism': 'optimism',
}

POA_NETWORKS: set[EvmNetwork] = {'bnb', 'avalanche', 'optimism'}
