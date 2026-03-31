from typing_extensions import TYPE_CHECKING, TypedDict
from dataclasses import dataclass, field
from . import TradingMarkets, TradingVenue

if TYPE_CHECKING:
  from dydx_sdk import Settings as DydxSettings
  from hyperliquid_sdk import Settings as HyperliquidSettings
  from mexc_sdk import Settings as MexcSettings

  class Settings(TypedDict, total=False):
    dydx: DydxSettings
    hyperliquid: HyperliquidSettings
    mexc: MexcSettings

SUPPORTED_VENUES = (
  'dydx',
  'dydx_testnet',
  'hyperliquid',
  'hyperliquid_testnet',
  'mexc',
)

@dataclass(frozen=True)
class TradingSDK(TradingMarkets):
  settings: 'Settings' = field(default_factory=lambda: {})

  def dydx(self, mainnet: bool = True):
    try:
      from dydx_sdk import DydxMarket
      return DydxMarket.new(mainnet=mainnet, settings=self.settings.get('dydx', {}))
    except ImportError:
      raise ImportError('dydx market is not installed. Please install it with `pip install dydx-trading-sdk`.')

  def hyperliquid(self, mainnet: bool = True):
    try:
      from hyperliquid_sdk import HyperliquidMarket
      return HyperliquidMarket.http(mainnet=mainnet, settings=self.settings.get('hyperliquid', {}))
    except ImportError:
      raise ImportError('hyperliquid market is not installed. Please install it with `pip install hyperliquid-trading-sdk`.')

  def mexc(self):
    try:
      from mexc_sdk import MexcMarket
      return MexcMarket.new(settings=self.settings.get('mexc', {}))
    except ImportError:
      raise ImportError('mexc market is not installed. Please install it with `pip install mexc-trading-sdk`.')

  async def venue(self, id: str, /) -> TradingVenue:
    match id:
      case 'dydx':
        return self.dydx()
      case 'dydx_testnet':
        return self.dydx(mainnet=False)
      case 'hyperliquid':
        return self.hyperliquid()
      case 'hyperliquid_testnet':
        return self.hyperliquid(mainnet=False)
      case 'mexc':
        return self.mexc()
      case _:
        raise ValueError(f'Invalid venue ID: {id}. Supported venues: {SUPPORTED_VENUES}')

  async def venues(self):
    return SUPPORTED_VENUES