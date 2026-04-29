from . import Earn

SUPPORTED_VENUES = (
  'binance',
  'bitget',
  'mexc',
)

class EarnSDK:
  def binance(self, **credentials: str) -> Earn:
    try:
      from tribulnation.binance import Binance
      return Binance.new(**credentials, validate=True).earn
    except ImportError:
      raise ImportError('binance sdk is not installed. Please install it with `pip install tribulnation-binance`.')

  def bitget(self, **credentials: str) -> Earn:
    try:
      from tribulnation.bitget import Bitget
      return Bitget.new(**credentials, validate=True).earn
    except ImportError:
      raise ImportError('bitget sdk is not installed. Please install it with `pip install tribulnation-bitget`.')

  def mexc(self, **credentials: str) -> Earn:
    try:
      from tribulnation.mexc.earn import Earn as MEXC
      return MEXC()
    except ImportError:
      raise ImportError('mexc sdk is not installed. Please install it with `pip install tribulnation-mexc`.')

  def all(self, credentials: dict[str, dict[str, str]] = {}) -> dict[str, Earn]:
    return {
      'binance': self.binance(**credentials.get('binance', {})),
      'bitget': self.bitget(**credentials.get('bitget', {})),
      'mexc': self.mexc(**credentials.get('mexc', {})),
    }

  async def venue(self, id: str, /, **credentials: str) -> Earn:
    match id:
      case 'binance':
        return self.binance(**credentials)
      case 'bitget':
        return self.bitget(**credentials)
      case 'mexc':
        return self.mexc(**credentials)
      case _:
        raise ValueError(f'Invalid venue ID: {id}. Supported venues: {SUPPORTED_VENUES}')

  async def venues(self):
    return SUPPORTED_VENUES