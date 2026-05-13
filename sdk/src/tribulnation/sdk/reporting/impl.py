from . import Report

def parse_bool(value: str | None, *, default: bool) -> bool:
  """Parse a string boolean used by generic venue credentials."""
  if value is None:
    return default
  return value.lower() not in {'0', 'false', 'no'}

SUPPORTED_VENUES = (
  'ethereum',
  'arbitrum',
  'polygon',
  'bnb',
  'base',
  'avalanche',
  'optimism',
  'dydx',
)

class ReportSDK:

  def ethereum(self, **credentials: str) -> Report:
    try:
      from tribulnation.ethereum.reporting import ethereum
      return ethereum(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def arbitrum(self, **credentials: str) -> Report:
    try:
      from tribulnation.ethereum.reporting import arbitrum
      return arbitrum(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def polygon(self, **credentials: str) -> Report:
    try:
      from tribulnation.ethereum.reporting import polygon
      return polygon(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def bnb(self, **credentials: str) -> Report:
    try:
      from tribulnation.ethereum.reporting import bnb
      return bnb(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def base(self, **credentials: str) -> Report:
    try:
      from tribulnation.ethereum.reporting import base
      return base(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def avalanche(self, **credentials: str) -> Report:
    try:
      from tribulnation.ethereum.reporting import avalanche
      return avalanche(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')
  
  def optimism(self, **credentials: str) -> Report:
    try:
      from tribulnation.ethereum.reporting import optimism
      return optimism(**credentials)
    except ImportError:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.')

  def dydx(self, address: str | None = None, *, mainnet: bool = True, validate: bool = True) -> Report:
    """Create a dYdX reporting client."""
    try:
      from tribulnation.dydx import Reporting
      return Reporting.new(address, mainnet=mainnet, validate=validate)
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
      'dydx': self.dydx_from_credentials(credentials.get('dydx', {})),
    }

  def dydx_from_credentials(self, credentials: dict[str, str]) -> Report:
    """Create a dYdX reporting client from generic credential strings."""
    return self.dydx(
      credentials.get('address'),
      mainnet=parse_bool(credentials.get('mainnet'), default=True),
      validate=parse_bool(credentials.get('validate'), default=True),
    )

  def venue(self, id: str, /, **credentials: str) -> Report:
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
        return self.dydx_from_credentials(credentials)
      case _:
        raise ValueError(f'Invalid venue ID: {id}. Supported venues: {SUPPORTED_VENUES}')

  def venues(self):
    return SUPPORTED_VENUES
