from typing_extensions import Literal, NewType, TypeGuard
import re

EthereumNetwork = NewType('EthereumNetwork', str)
"""`Ethereum::{chain_id}`"""
ETHEREUM_NETWORK_PATTERN = re.compile(r'^Ethereum::(\d+)$')

def is_ethereum_network(s: str) -> TypeGuard[EthereumNetwork]:
  return ETHEREUM_NETWORK_PATTERN.match(s) is not None

def ethereum_network(chain_id: int) -> EthereumNetwork:
  return EthereumNetwork(f'Ethereum::{chain_id}')

OtherNetwork = Literal[
  'Bitcoin',
  'Bitcoin::ARC20',
  'Bitcoin::BRC20',
  'Bitcoin::Runes',
  'Solana',
  'The Open Network',
  'Tron',
  'Aptos',
  'Cardano',
  'Neo',
  'Terra',
  'Hyperliquid',
  'Merlin',
  'Starknet',
  'XRP',
  'Stacks',
  'AB Core',
  'Lightning',
  'Litecoin',
  'Noble',
  'Dogecoin',
  'Zcash',
  'Cosmos',
  'Tezos',
]
OTHER_NETWORKS: set[OtherNetwork] = set(OtherNetwork)
Network = EthereumNetwork | OtherNetwork



def is_network(s: str) -> TypeGuard[Network]:
  return s in OTHER_NETWORKS or is_ethereum_network(s)