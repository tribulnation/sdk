from typing_extensions import Mapping, TypedDict, TYPE_CHECKING
from dataclasses import dataclass, field
from pathlib import Path

from tribulnation.sdk.reporting import Report
from tribulnation.sdk.reporting.config import ProvidersConfig
from .accounts import (
  Account,
  Dydx,
  Evm,
  Binance,
  Bitget,
  Bit2Me,
  Bybit,
  Coinbase,
  Kraken,
  Kucoin,
  Deribit,
  Mexc,
  Hyperliquid,
  load_accounts,
)


if TYPE_CHECKING:
  from tribulnation.ethereum.reporting import EvmConfig
  from tribulnation.dydx.report import DydxConfig
  from tribulnation.hyperliquid.report import HyperliquidConfig

  class Config(TypedDict, total=False):
    evm: EvmConfig
    dydx: DydxConfig
    hyperliquid: HyperliquidConfig
else:
  Config = dict


@dataclass
class ReportSDK:
  accounts: Mapping[str, Account]
  providers: ProvidersConfig | None = field(default=None, kw_only=True)
  config: 'Config' = field(default_factory=Config, kw_only=True)

  @classmethod
  def load(cls, path: Path | str = 'sdk.toml') -> 'ReportSDK':
    """Construct a `ReportSDK` from a TOML file's `[accounts.<id>]` tables.

    Args:
      path: Path to a TOML file with an `[accounts]` table.
    """
    return cls(accounts=load_accounts(path))

  def evm(self, account: Evm, id: str) -> Report:
    try:
      from tribulnation.ethereum.reporting import EthereumReport
    except ImportError as e:
      raise ImportError(
        'ethereum sdk is not installed. Please install it with `pip install tribulnation-ethereum`.'
      ) from e
    if (address := account.resolved_address) is None:
      raise ValueError(f'Account {id} does not have a resolved address.')
    return EthereumReport.new(
      address,
      network=account.venue,
      providers=self.providers,
      config=self.config.get('evm'),
    )

  def dydx(self, account: Dydx, id: str) -> Report:
    try:
      from tribulnation.dydx import Report as DydxReport
    except ImportError as e:
      raise ImportError(
        'dydx sdk is not installed. Please install it with `pip install tribulnation-dydx`.'
      ) from e
    if (address := account.resolved_address) is None:
      raise ValueError(f'Account {id} does not have a resolved address.')
    return DydxReport.new(
      address,
      providers=self.providers,
      config={**(self.config.get('dydx') or {}), 'mainnet': account.venue == 'dydx'},
    )

  def binance(self, account: Binance, id: str) -> Report:
    try:
      from tribulnation.binance import Reporting as BinanceReport
    except ImportError as e:
      raise ImportError(
        'binance sdk is not installed. Please install it with `pip install tribulnation-binance`.'
      ) from e
    return BinanceReport.new(
      account.resolved_api_key,
      account.resolved_secret_key,
      validate=account.validate,
    )

  def coinbase(self, account: Coinbase, id: str) -> Report:
    try:
      from tribulnation.coinbase import Report as CoinbaseReport
    except ImportError as e:
      raise ImportError(
        'coinbase sdk is not installed. Please install it with `pip install tribulnation-coinbase`.'
      ) from e
    return CoinbaseReport.new(account.resolved_key_name, account.resolved_private_key)

  def bybit(self, account: Bybit, id: str) -> Report:
    try:
      from tribulnation.bybit import Report as BybitReport
    except ImportError as e:
      raise ImportError(
        'bybit sdk is not installed. Please install it with `pip install tribulnation-bybit`.'
      ) from e
    return BybitReport.new(
      account.resolved_api_key,
      account.resolved_api_secret,
      settings={'validate': account.validate},
    )

  def bitget(self, account: Bitget, id: str) -> Report:
    raise NotImplementedError(
      'bitget reporting is not wired: the existing implementation targets classic '
      'accounts, which the unified trading account (UTA) does not support.'
    )

  def mexc(self, account: Mexc, id: str) -> Report:
    try:
      from tribulnation.mexc.reporting import Report as MexcReport
    except ImportError as e:
      raise ImportError(
        'mexc sdk is not installed. Please install it with `pip install tribulnation-mexc`.'
      ) from e
    return MexcReport.new(
      account.resolved_api_key,
      account.resolved_api_secret,
      settings={'validate': account.validate},
    )

  def bit2me(self, account: Bit2Me, id: str) -> Report:
    try:
      from tribulnation.bit2me.report import Report as Bit2MeReport
    except ImportError as e:
      raise ImportError(
        'bit2me sdk is not installed. Please install it with `pip install tribulnation-bit2me`.'
      ) from e
    return Bit2MeReport.new(
      account.resolved_api_key,
      account.resolved_api_secret,
      validate=account.validate,
    )

  def kucoin(self, account: Kucoin, id: str) -> Report:
    """Build Kucoin's report surface with the account credentials."""
    try:
      from tribulnation.kucoin import Report as KucoinReport
    except ImportError as exception:
      raise ImportError('Install tribulnation-kucoin to use this venue.') from exception
    return KucoinReport.new(
      account.resolved_api_key,
      account.resolved_api_secret,
      account.resolved_api_passphrase,
      public=account.public,
      validate=account.validate,
    )

  def deribit(self, account: Deribit, id: str) -> Report:
    """Build Deribit's report surface in the explicitly selected environment."""
    try:
      from tribulnation.deribit import Report as DeribitReport
    except ImportError as exception:
      raise ImportError(
        'Install tribulnation-deribit to use this venue.'
      ) from exception
    return DeribitReport.new(
      account.resolved_client_id,
      account.resolved_client_secret,
      public=account.public,
      validate=account.validate,
      testnet=account.venue == 'deribit_testnet',
    )

  def kraken(self, account: Kraken, id: str) -> Report:
    try:
      from tribulnation.kraken import Report as KrakenReport
    except ImportError as e:
      raise ImportError(
        'kraken sdk is not installed. Please install it with `pip install tribulnation-kraken`.'
      ) from e
    return KrakenReport.new(
      account.resolved_api_key,
      account.resolved_private_key,
      validate=account.validate,
    )

  def hyperliquid(self, account: Hyperliquid, id: str) -> Report:
    try:
      from tribulnation.hyperliquid import Report as HyperliquidReport
    except ImportError as e:
      raise ImportError(
        'hyperliquid sdk is not installed. Please install it with `pip install tribulnation-hyperliquid`.'
      ) from e
    if (address := account.resolved_address) is None:
      raise ValueError(f'Account {id} does not have a resolved address.')
    return HyperliquidReport.new(
      address,
      config={
        **(self.config.get('hyperliquid') or {}),
        'mainnet': account.venue == 'hyperliquid',
      },
    )

  def venue(self, id: str, /) -> Report:
    if (account := self.accounts.get(id)) is None:
      raise ValueError(f'No account found for venue id: {id}')
    match account.venue:
      case (
        'ethereum'
        | 'arbitrum'
        | 'polygon'
        | 'bnb-chain'
        | 'base'
        | 'avalanche'
        | 'optimism'
        | 'hyperevm'
      ):
        return self.evm(account, id)
      case 'dydx' | 'dydx_testnet':
        return self.dydx(account, id)
      case 'binance':
        return self.binance(account, id)
      case 'bitget':
        return self.bitget(account, id)
      case 'mexc':
        return self.mexc(account, id)
      case 'bit2me':
        return self.bit2me(account, id)
      case 'coinbase':
        return self.coinbase(account, id)
      case 'bybit':
        return self.bybit(account, id)
      case 'hyperliquid' | 'hyperliquid_testnet':
        return self.hyperliquid(account, id)
      case 'kraken':
        return self.kraken(account, id)
      case 'kucoin':
        return self.kucoin(account, id)
      case 'deribit' | 'deribit_testnet':
        return self.deribit(account, id)
      case _:
        raise ValueError(f'Unsupported venue: {account.venue}')

  @property
  def all(self) -> dict[str, Report]:
    return {id: self.venue(id) for id in self.accounts}
