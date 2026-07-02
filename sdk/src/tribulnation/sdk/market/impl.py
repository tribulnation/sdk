from typing_extensions import TypedDict
from dataclasses import dataclass, field
from . import TradingMarkets, TradingVenue


class _DydxConfig(TypedDict, total=False):
  validate: bool
  parent_subaccount: int


class _HyperliquidConfig(TypedDict, total=False):
  validate: bool


class _MexcConfig(TypedDict, total=False):
  validate: bool
  recvWindow: int


class Settings(TypedDict, total=False):
  dydx: _DydxConfig
  hyperliquid: _HyperliquidConfig
  mexc: _MexcConfig


SUPPORTED_VENUES = (
  'dydx',
  'dydx_testnet',
  'hyperliquid',
  'hyperliquid_testnet',
  'mexc',
)

@dataclass(frozen=True)
class TradingSDK(TradingMarkets):
  settings: Settings = field(default_factory=lambda: {})

  def dydx(self, *, mainnet: bool = True, **credentials: str):
    try:
      from tribulnation.dydx import DydxMarket
      s = self.settings.get('dydx', {})
      return DydxMarket.new(mainnet=mainnet, validate=s.get('validate', True), parent_subaccount=s.get('parent_subaccount', 0), **credentials)
    except ImportError:
      raise ImportError('dydx market is not installed. Please install it with `pip install tribulnation-dydx`.')

  def hyperliquid(self, *, mainnet: bool = True, **credentials: str):
    try:
      from tribulnation.hyperliquid import HyperliquidMarket
      s = self.settings.get('hyperliquid', {})
      return HyperliquidMarket.http(mainnet=mainnet, validate=s.get('validate', True), **credentials)
    except ImportError:
      raise ImportError('hyperliquid market is not installed. Please install it with `pip install tribulnation-hyperliquid`.')

  def mexc(self, **credentials: str):
    try:
      from tribulnation.mexc import MexcMarket
      s = self.settings.get('mexc', {})
      return MexcMarket.new(validate=s.get('validate', True), recv_window=s.get('recvWindow'), **credentials)
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