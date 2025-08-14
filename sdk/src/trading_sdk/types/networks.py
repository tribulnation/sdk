from typing_extensions import Literal, Union

BinanceSmartChain = Literal['BSC']
Ethereum = Literal['ETH']
Polygon = Literal['POL']
Tron = Literal['TRX']
Arbitrum = Literal['ARB']
Base = Literal['BASE']
Avalanche = Literal['AVAX']
Solana = Literal['SOL']
Fantom = Literal['FTM']
Optimism = Literal['OP']
TheOpenNetwork = Literal['TON']
Sonic = Literal['SONIC']
Tezos = Literal['XTZ']
Core = Literal['CORE']
Celo = Literal['CELO']
Near = Literal['NEAR']
Mantle = Literal['MNT']
Unichain = Literal['UNI']

Network = Union[
  BinanceSmartChain,
  Ethereum,
  Polygon,
  Tron,
  Arbitrum,
  Base,
  Avalanche,
  Solana,
  Fantom,
  Optimism,
  TheOpenNetwork,
  Sonic,
  Tezos,
  Core,
  Celo,
  Near,
  Mantle,
  Unichain,
]