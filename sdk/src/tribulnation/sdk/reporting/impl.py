"""Top-level reporting SDK venue dispatcher."""

from typing_extensions import TYPE_CHECKING, TypedDict
from dataclasses import dataclass, field
from tribulnation.sdk import SDK
from . import Report

if TYPE_CHECKING:
  from tribulnation.dydx.report import DydxConfig
  from tribulnation.ethereum.reporting import EvmConfig
  from .config import ProvidersConfig

  class Settings(TypedDict, total=False):
    providers: ProvidersConfig
    dydx: DydxConfig
    ethereum: EvmConfig
    arbitrum: EvmConfig
    polygon: EvmConfig
    bnb: EvmConfig
    base: EvmConfig
    avalanche: EvmConfig
    optimism: EvmConfig

SUPPORTED_VENUES = (
  'ethereum',
  'arbitrum',
  'polygon',
  'bnb_chain',
  'base',
  'avalanche',
  'optimism',
  'dydx',
)

@dataclass(frozen=True)
class ReportSDK(SDK):
  """Factory for venue-specific reporting clients."""
  settings: 'Settings' = field(default_factory=lambda: {})

  def ethereum(self, address: str) -> Report:
    """Create an Ethereum mainnet reporting client."""
    try:
      from tribulnation.ethereum.reporting import EthereumReport
      return EthereumReport.new(
        address,
        network='ethereum',
        config=self.settings.get('ethereum'),
        providers=self.settings.get('providers'),
      )
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def arbitrum(self, address: str) -> Report:
    """Create an Arbitrum reporting client."""
    try:
      from tribulnation.ethereum.reporting import EthereumReport
      return EthereumReport.new(
        address,
        network='arbitrum',
        config=self.settings.get('arbitrum'),
        providers=self.settings.get('providers'),
      )
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def polygon(self, address: str) -> Report:
    """Create a Polygon reporting client."""
    try:
      from tribulnation.ethereum.reporting import EthereumReport
      return EthereumReport.new(
        address,
        network='polygon',
        config=self.settings.get('polygon'),
        providers=self.settings.get('providers'),
      )
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def bnb(self, address: str) -> Report:
    """Create a BNB Chain reporting client."""
    try:
      from tribulnation.ethereum.reporting import EthereumReport
      return EthereumReport.new(
        address,
        network='bnb',
        config=self.settings.get('bnb'),
        providers=self.settings.get('providers'),
      )
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def base(self, address: str) -> Report:
    """Create a Base reporting client."""
    try:
      from tribulnation.ethereum.reporting import EthereumReport
      return EthereumReport.new(
        address,
        network='base',
        config=self.settings.get('base'),
        providers=self.settings.get('providers'),
      )
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def avalanche(self, address: str) -> Report:
    """Create an Avalanche reporting client."""
    try:
      from tribulnation.ethereum.reporting import EthereumReport
      return EthereumReport.new(
        address,
        network='avalanche',
        config=self.settings.get('avalanche'),
        providers=self.settings.get('providers'),
      )
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def optimism(self, address: str) -> Report:
    """Create an Optimism reporting client."""
    try:
      from tribulnation.ethereum.reporting import EthereumReport
      return EthereumReport.new(
        address,
        network='optimism',
        config=self.settings.get('optimism'),
        providers=self.settings.get('providers'),
      )
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')

  def dydx(self, address: str) -> Report:
    """Create a dYdX reporting client."""
    try:
      from tribulnation.dydx import Report as DydxReport
      return DydxReport.new(
        address,
        config=self.settings.get('dydx'),
        providers=self.settings.get('providers'),
      )
    except ImportError:
      raise ImportError('dydx sdk is not installed. Please install it with `pip install tribulnation-dydx`.')

  def all(self, credentials: dict[str, dict[str, str]] | None = None) -> dict[str, Report]:
    """Create reporting clients for every supported venue."""
    credentials = credentials or {}
    return {
      'ethereum': self.ethereum(**credentials.get('ethereum', {})),
      'arbitrum': self.arbitrum(**credentials.get('arbitrum', {})),
      'polygon': self.polygon(**credentials.get('polygon', {})),
      'bnb_chain': self.bnb(**credentials.get('bnb_chain', {})),
      'base': self.base(**credentials.get('base', {})),
      'avalanche': self.avalanche(**credentials.get('avalanche', {})),
      'optimism': self.optimism(**credentials.get('optimism', {})),
      'dydx': self.dydx(**credentials.get('dydx', {})),
    }


  def venue(self, id: str, /, **credentials) -> Report:
    """Create a reporting client by venue id."""
    match id:
      case 'ethereum':
        return self.ethereum(**credentials)
      case 'arbitrum':
        return self.arbitrum(**credentials)
      case 'polygon':
        return self.polygon(**credentials)
      case 'bnb_chain':
        return self.bnb(**credentials)
      case 'base':
        return self.base(**credentials)
      case 'avalanche':
        return self.avalanche(**credentials)
      case 'optimism':
        return self.optimism(**credentials)
      case 'dydx':
        return self.dydx(**credentials)
      case _:
        raise ValueError(f'Invalid venue ID: {id}. Supported venues: {SUPPORTED_VENUES}')

  def venues(self):
    """Return supported venue ids."""
    return SUPPORTED_VENUES
