from dataclasses import dataclass
from . import TradingMarkets, TradingVenue

SUPPORTED_VENUES = (
  'dydx',
  'dydx_testnet',
  'hyperliquid',
  'hyperliquid_testnet',
  'mexc',
)

def load_dydx(mainnet: bool = True):
  try:
    from dydx_sdk import DydxMarket
    return DydxMarket.new(mainnet=mainnet)
  except ImportError:
    raise ImportError('dydx market is not installed. Please install it with `pip install dydx-trading-sdk`.')

def load_hyperliquid(mainnet: bool = True):
  try:
    from hyperliquid_sdk import HyperliquidMarket
    return HyperliquidMarket.http(mainnet=mainnet)
  except ImportError:
    raise ImportError('hyperliquid market is not installed. Please install it with `pip install hyperliquid-trading-sdk`.')

def load_mexc():
  try:
    from mexc_sdk import MexcMarket
    return MexcMarket.new()
  except ImportError:
    raise ImportError('mexc market is not installed. Please install it with `pip install mexc-trading-sdk`.')

@dataclass(frozen=True)
class TradingSDK(TradingMarkets):

  async def venue(self, id: str, /) -> TradingVenue:
    match id:
      case 'dydx':
        return load_dydx()
      case 'dydx_testnet':
        return load_dydx(mainnet=False)
      case 'hyperliquid':
        return load_hyperliquid()
      case 'hyperliquid_testnet':
        return load_hyperliquid(mainnet=False)
      case 'mexc':
        return load_mexc()
      case _:
        raise ValueError(f'Invalid venue ID: {id}. Supported venues: {SUPPORTED_VENUES}')

  async def venues(self):
    return SUPPORTED_VENUES