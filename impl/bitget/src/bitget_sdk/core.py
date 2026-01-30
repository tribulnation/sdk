from dataclasses import dataclass
from sdk.core.networks import Network, ethereum_network

from bitget import Bitget

def parse_network(network: str) -> Network | None:
  match network:
    case 'ERC20' | 'ETH': return ethereum_network(1)
    case 'BEP20': return ethereum_network(56)
    case 'SOL': return 'Solana'
    case 'ArbitrumOne': return ethereum_network(42161)
    case 'BASE': return ethereum_network(8453)
    case 'Polygon' | 'POLYGON': return ethereum_network(137)
    case 'TON': return 'The Open Network'
    case 'BRC20': return 'Bitcoin::BRC20'
    case 'CAP20': return ethereum_network(1285)
    case 'SUI': return 'Sui'
    case 'AVAXC-Chain': return ethereum_network(43114)
    case 'Optimism' | 'OPTIMISM': return ethereum_network(10)
    case 'Kaia': return ethereum_network(8217)
    case 'TRC20': return 'Tron'
    case 'Aptos': return 'Aptos'
    case 'Morph': return ethereum_network(2818)
    case 'zkSyncEra': return ethereum_network(324)
    case 'Cardano': return 'Cardano'
    case 'RONIN': return ethereum_network(2020)
    case 'Fantom': return ethereum_network(250)
    case 'NEARProtocol': return ethereum_network(397)
    case 'OASYS': return ethereum_network(248)
    case 'HBAR': return ethereum_network(295)
    case 'Ontology': return ethereum_network(58)
    case 'MantaNetWork': return ethereum_network(169)
    case 'NEO3': return 'Neo'
    case 'Terra': return 'Terra'
    case 'HYPE' | 'HyperEvm': return 'Hyperliquid'
    case 'MERLIN': return 'Merlin'
    case 'BERA': return ethereum_network(80094)
    case 'CELO': return ethereum_network(42220)
    case 'SONIC': return ethereum_network(146)
    case 'BITCI': return ethereum_network(1907)
    case 'BTCRUNES': return 'Bitcoin::Runes'
    case 'Blast': return ethereum_network(81457)
    case 'Plasma': return ethereum_network(9745)
    case 'SCROLL': return ethereum_network(534352)
    case 'Starknet': return 'Starknet'
    case 'XRP' | 'XRPTOKEN': return 'XRP'
    case 'stacks': return 'Stacks'
    case 'Monad': return ethereum_network(143)
    case 'DYMEVM': return ethereum_network(1100)
    case 'MAPO': return ethereum_network(22776)
    case 'STORY': return ethereum_network(1514)
    case 'SEI' | 'SEIEVM': return ethereum_network(1329)
    case 'ZIL': return ethereum_network(32769)
    case 'ABCore': return 'AB Core'
    case 'VET': return ethereum_network(100009)
    case 'BTC': return 'Bitcoin'
    case 'LIGHTNING': return 'Lightning'
    case 'IOST': return ethereum_network(182)
    case 'LTC': return 'Litecoin'
    case 'Frax': return ethereum_network(252)
    case 'Noble': return 'Noble'
    case 'DOGE': return 'Dogecoin'
    case 'ZEC': return 'Zcash'
    case 'DOT': return ethereum_network(420420419)
    case 'ATOM': return 'Cosmos'
    case 'XTZ': return 'Tezos'


@dataclass
class SdkMixin:
  client: Bitget
  validate: bool = True

  @classmethod
  def new(
    cls, access_key: str | None = None, secret_key: str | None = None, passphrase: str | None = None, *,
    validate: bool = True
  ):
    client = Bitget.new(access_key=access_key, secret_key=secret_key, passphrase=passphrase)
    return cls(client=client, validate=validate)

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)