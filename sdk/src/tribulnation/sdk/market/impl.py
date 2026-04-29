from typing_extensions import TYPE_CHECKING, TypedDict
from dataclasses import dataclass, field
from . import TradingMarkets, TradingVenue

if TYPE_CHECKING:
  from tribulnation.dydx import Settings as DydxSettings
  from tribulnation.hyperliquid import Settings as HyperliquidSettings
  from tribulnation.mexc import Settings as MexcSettings

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

  def dydx(self, *, mainnet: bool = True, **credentials: str):
    try:
      from tribulnation.dydx import DydxMarket
      return DydxMarket.new(mainnet=mainnet, settings=self.settings.get('dydx', {}), **credentials)
    except ImportError:
      raise ImportError('dydx market is not installed. Please install it with `pip install tribulnation-dydx`.')

  def hyperliquid(self, *, mainnet: bool = True, **credentials: str):
    try:
      from tribulnation.hyperliquid import HyperliquidMarket
      return HyperliquidMarket.http(mainnet=mainnet, settings=self.settings.get('hyperliquid', {}), **credentials)
    except ImportError:
      raise ImportError('hyperliquid market is not installed. Please install it with `pip install tribulnation-hyperliquid`.')

  def mexc(self, **credentials: str):
    try:
      from tribulnation.mexc import MexcMarket
      return MexcMarket.new(settings=self.settings.get('mexc', {}), **credentials)
    except ImportError:
      raise ImportError('mexc market is not installed. Please install it with `pip install tribulnation-mexc`.')

  async def venue(self, id: str, /, **credentials: str) -> TradingVenue:
    match id:
      case 'dydx':
        return self.dydx(mainnet=True, **credentials)
      case 'dydx_testnet':
        return self.dydx(mainnet=False, **credentials)
      case 'hyperliquid':
        return self.hyperliquid(mainnet=True, **credentials)
      case 'hyperliquid_testnet':
        return self.hyperliquid(mainnet=False, **credentials)
      case 'mexc':
        return self.mexc(**credentials)
      case _:
        raise ValueError(f'Invalid venue ID: {id}. Supported venues: {SUPPORTED_VENUES}')

  async def venues(self):
    return SUPPORTED_VENUES