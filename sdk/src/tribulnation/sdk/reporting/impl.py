from typing_extensions import TYPE_CHECKING, TypedDict
from dataclasses import dataclass, field
from tribulnation.sdk import SDK
from . import Report

if TYPE_CHECKING:
  from tribulnation.dydx.report import Settings as DydxSettings

  class Settings(TypedDict, total=False):
    dydx: DydxSettings

SUPPORTED_VENUES = (
  'ethereum',
  'arbitrum',
  'polygon',
  'bnb',
  'base',
  'avalanche',
  'optimism',
  'dydx',
  'dydx_testnet',
)

@dataclass(frozen=True)
class ReportSDK(SDK):
  settings: 'Settings' = field(default_factory=lambda: {})

  def ethereum(self, **credentials) -> Report:
    try:
      from tribulnation.ethereum.reporting import ethereum
      return ethereum(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def arbitrum(self, **credentials) -> Report:
    try:
      from tribulnation.ethereum.reporting import arbitrum
      return arbitrum(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def polygon(self, **credentials) -> Report:
    try:
      from tribulnation.ethereum.reporting import polygon
      return polygon(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def bnb(self, **credentials) -> Report:
    try:
      from tribulnation.ethereum.reporting import bnb
      return bnb(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def base(self, **credentials) -> Report:
    try:
      from tribulnation.ethereum.reporting import base
      return base(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def avalanche(self, **credentials) -> Report:
    try:
      from tribulnation.ethereum.reporting import avalanche
      return avalanche(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def optimism(self, **credentials) -> Report:
    try:
      from tribulnation.ethereum.reporting import optimism
      return optimism(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')

  def dydx(self, *, mainnet: bool = True, **credentials) -> Report:
    """Create a dYdX reporting client."""
    try:
      from tribulnation.dydx import Reporting
      return Reporting.new(mainnet=mainnet, **credentials, **self.settings.get('dydx', {}))
    except ImportError:
      raise ImportError('dydx sdk is not installed. Please install it with `pip install tribulnation-dydx`.')

  def all(self, credentials: dict[str, dict[str, str]] = {}) -> dict[str, Report]:
    return {
      'ethereum': self.ethereum(**credentials.get('ethereum', {})),
      'arbitrum': self.arbitrum(**credentials.get('arbitrum', {})),
      'polygon': self.polygon(**credentials.get('polygon', {})),
      'bnb': self.bnb(**credentials.get('bnb', {})),
      'base': self.base(**credentials.get('base', {})),
      'avalanche': self.avalanche(**credentials.get('avalanche', {})),
      'optimism': self.optimism(**credentials.get('optimism', {})),
      'dydx': self.dydx(mainnet=True, **credentials.get('dydx', {})),
      'dydx_testnet': self.dydx(mainnet=False, **credentials.get('dydx_testnet', {})),
    }


  def venue(self, id: str, /, **credentials) -> Report:
    match id:
      case 'ethereum':
        return self.ethereum(**credentials)
      case 'arbitrum':
        return self.arbitrum(**credentials)
      case 'polygon':
        return self.polygon(**credentials)
      case 'bnb':
        return self.bnb(**credentials)
      case 'base':
        return self.base(**credentials)
      case 'avalanche':
        return self.avalanche(**credentials)
      case 'optimism':
        return self.optimism(**credentials)
      case 'dydx':
        return self.dydx(mainnet=True, **credentials)
      case 'dydx_testnet':
        return self.dydx(mainnet=False, **credentials)
      case _:
        raise ValueError(f'Invalid venue ID: {id}. Supported venues: {SUPPORTED_VENUES}')

  def venues(self):
    return SUPPORTED_VENUES
