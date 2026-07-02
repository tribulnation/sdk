from typing_extensions import Mapping
from dataclasses import dataclass, field

from tribulnation.sdk.reporting import Report
from tribulnation.sdk.reporting.config import ProvidersConfig
from .accounts import Account, Dydx, Evm, Binance, Bitget, Mexc


@dataclass
class ReportSDK:
  accounts: Mapping[str, Account]
  providers: ProvidersConfig = field(default_factory=ProvidersConfig)

  def evm(self, account: Evm) -> Report:
    try:
      from tribulnation.ethereum.reporting import EthereumReport
    except ImportError as e:
      raise ImportError('ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.') from e
    return EthereumReport.new(account.resolved_address, network=account.venue, providers=self.providers or None)

  def dydx(self, account: Dydx) -> Report:
    try:
      from tribulnation.dydx import Report as DydxReport
    except ImportError as e:
      raise ImportError('dydx sdk is not installed. Please install it with `pip install tribulnation-dydx`.') from e
    return DydxReport.new(account.resolved_address, providers=self.providers or None)

  def binance(self, account: Binance) -> Report:
    raise NotImplementedError('binance reporting is not yet implemented.')

  def bitget(self, account: Bitget) -> Report:
    raise NotImplementedError('bitget reporting is not yet implemented.')

  def mexc(self, account: Mexc) -> Report:
    raise NotImplementedError('mexc reporting is not yet implemented.')

  def venue(self, id: str, /) -> Report:
    if (account := self.accounts.get(id)) is None:
      raise ValueError(f'No account found for venue id: {id}')
    match account.venue:
      case 'ethereum' | 'arbitrum' | 'polygon' | 'bnb-chain' | 'base' | 'avalanche' | 'optimism':
        return self.evm(account)
      case 'dydx' | 'dydx_testnet':
        return self.dydx(account)
      case 'binance':
        return self.binance(account)
      case 'bitget':
        return self.bitget(account)
      case 'mexc':
        return self.mexc(account)
      case _:
        raise ValueError(f'Unsupported venue: {account.venue}')

  @property
  def all(self) -> dict[str, Report]:
    return {id: self.venue(id) for id in self.accounts}
