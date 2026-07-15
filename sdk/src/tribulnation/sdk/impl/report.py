from typing_extensions import Mapping, TypedDict, TYPE_CHECKING
from dataclasses import dataclass, field

from tribulnation.sdk.reporting import Report
from tribulnation.sdk.reporting.config import ProvidersConfig
from .accounts import Account, Dydx, Evm, Binance, Bitget, Mexc, Hyperliquid

if TYPE_CHECKING:
  from tribulnation.ethereum.reporting import EvmConfig
  from tribulnation.dydx.report import DydxConfig

  class Config(TypedDict, total=False):
    evm: EvmConfig
    dydx: DydxConfig
else:
  Config = dict

@dataclass
class ReportSDK:
  accounts: Mapping[str, Account]
  providers: ProvidersConfig | None = field(default=None, kw_only=True)
  config: 'Config' = field(default_factory=Config, kw_only=True)

  def evm(self, account: Evm, id: str) -> Report:
    try:
      from tribulnation.ethereum.reporting import EthereumReport
    except ImportError as e:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.') from e
    if (address := account.resolved_address) is None:
      raise ValueError(f'Account {id} does not have a resolved address.')
    return EthereumReport.new(address, network=account.venue, providers=self.providers, config=self.config.get('evm'))

  def dydx(self, account: Dydx, id: str) -> Report:
    try:
      from tribulnation.dydx import Report as DydxReport
    except ImportError as e:
      raise ImportError('dydx sdk is not installed. Please install it with `pip install tribulnation-dydx`.') from e
    if (address := account.resolved_address) is None:
      raise ValueError(f'Account {id} does not have a resolved address.')
    return DydxReport.new(address, providers=self.providers, config=self.config.get('dydx'))

  def binance(self, account: Binance, id: str) -> Report:
    raise NotImplementedError('binance reporting is not yet implemented.')

  def bitget(self, account: Bitget, id: str) -> Report:
    raise NotImplementedError('bitget reporting is not yet implemented.')

  def mexc(self, account: Mexc, id: str) -> Report:
    raise NotImplementedError('mexc reporting is not yet implemented.')

  def hyperliquid(self, account: Hyperliquid, id: str) -> Report:
    raise NotImplementedError('hyperliquid reporting is not yet implemented.')

  def venue(self, id: str, /) -> Report:
    if (account := self.accounts.get(id)) is None:
      raise ValueError(f'No account found for venue id: {id}')
    match account.venue:
      case 'ethereum' | 'arbitrum' | 'polygon' | 'bnb-chain' | 'base' | 'avalanche' | 'optimism':
        return self.evm(account, id)
      case 'dydx' | 'dydx_testnet':
        return self.dydx(account, id)
      case 'binance':
        return self.binance(account, id)
      case 'bitget':
        return self.bitget(account, id)
      case 'mexc':
        return self.mexc(account, id)
      case 'hyperliquid':
        return self.hyperliquid(account, id)
      case _:
        raise ValueError(f'Unsupported venue: {account.venue}')

  @property
  def all(self) -> dict[str, Report]:
    return {id: self.venue(id) for id in self.accounts}
