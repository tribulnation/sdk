from typing_extensions import Mapping
from dataclasses import dataclass, field

from tribulnation.sdk.wallet import Wallet
from .accounts import Account, Mexc, Bitget, Binance

DEFAULT_ACCOUNTS: Mapping[str, Account] = {}

@dataclass
class WalletSDK:
  accounts: Mapping[str, Account] = field(default_factory=dict)

  @property
  def all_accounts(self) -> Mapping[str, Account]:
    return {**DEFAULT_ACCOUNTS, **self.accounts}

  def binance(self, account: Binance) -> Wallet:
    try:
      from tribulnation.binance import Binance as BinanceClient
    except ImportError as e:
      raise ImportError('binance sdk is not installed. Please install it with `pip install tribulnation-binance`.') from e
    return BinanceClient.new(api_key=account.resolved_api_key, api_secret=account.resolved_api_secret, validate=account.validate).wallet

  def bitget(self, account: Bitget) -> Wallet:
    try:
      from tribulnation.bitget import Bitget as BitgetClient
    except ImportError as e:
      raise ImportError('bitget sdk is not installed. Please install it with `pip install tribulnation-bitget`.') from e
    return BitgetClient.new(access_key=account.resolved_access_key, secret_key=account.resolved_secret_key, passphrase=account.resolved_passphrase, validate=account.validate).wallet

  def mexc(self, account: Mexc) -> Wallet:
    try:
      from tribulnation.mexc import MEXC
    except ImportError as e:
      raise ImportError('mexc sdk is not installed. Please install it with `pip install tribulnation-mexc`.') from e
    return MEXC.new(api_key=account.resolved_api_key, api_secret=account.resolved_api_secret, settings={'validate': account.validate}).wallet

  @property
  def all(self) -> dict[str, Wallet]:
    return {id: self.venue(id) for id in self.all_accounts}

  def venue(self, id: str, /) -> Wallet:
    if (account := self.all_accounts.get(id)) is None:
      raise ValueError(f'No account found for venue id: {id}')
    match account.venue:
      case 'binance':
        return self.binance(account)
      case 'bitget':
        return self.bitget(account)
      case 'mexc':
        return self.mexc(account)
      case _:
        raise ValueError(f'Unsupported venue: {account.venue}')

  def venues(self) -> list[str]:
    return list(self.all_accounts)
