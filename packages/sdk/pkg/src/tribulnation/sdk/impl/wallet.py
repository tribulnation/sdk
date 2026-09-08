from typing_extensions import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tribulnation.sdk.wallet import Wallet
from .accounts import (
  Account,
  Bit2Me,
  Bybit,
  Kraken,
  Mexc,
  Bitget,
  Binance,
  load_accounts,
)

DEFAULT_ACCOUNTS: Mapping[str, Account] = {}


@dataclass
class WalletSDK:
  accounts: Mapping[str, Account] = field(default_factory=dict[str, Account])

  @property
  def all_accounts(self) -> Mapping[str, Account]:
    return {**DEFAULT_ACCOUNTS, **self.accounts}

  @classmethod
  def load(cls, path: Path | str = 'sdk.toml') -> 'WalletSDK':
    """Construct a `WalletSDK` from a TOML file's `[accounts.<id>]` tables.

    Args:
      path: Path to a TOML file with an `[accounts]` table.
    """
    return cls(accounts=load_accounts(path))

  def binance(self, account: Binance) -> Wallet:
    try:
      from tribulnation.binance import Binance as BinanceClient
    except ImportError as e:
      raise ImportError(
        'binance sdk is not installed. Please install it with `pip install tribulnation-binance`.'
      ) from e
    return BinanceClient.new(
      api_key=account.resolved_api_key,
      secret_key=account.resolved_secret_key,
      validate=account.validate,
    ).wallet

  def bitget(self, account: Bitget) -> Wallet:
    try:
      from tribulnation.bitget import Bitget as BitgetClient
    except ImportError as e:
      raise ImportError(
        'bitget sdk is not installed. Please install it with `pip install tribulnation-bitget`.'
      ) from e
    return BitgetClient.new(
      access_key=account.resolved_access_key,
      secret_key=account.resolved_secret_key,
      passphrase=account.resolved_passphrase,
      uta=account.uta,
      validate=account.validate,
    ).wallet

  def mexc(self, account: Mexc) -> Wallet:
    try:
      from tribulnation.mexc import MEXC
    except ImportError as e:
      raise ImportError(
        'mexc sdk is not installed. Please install it with `pip install tribulnation-mexc`.'
      ) from e
    return MEXC.new(
      api_key=account.resolved_api_key,
      api_secret=account.resolved_api_secret,
      settings={'validate': account.validate},
    ).wallet

  def bybit(self, account: Bybit) -> Wallet:
    try:
      from tribulnation.bybit import Wallet as BybitWallet
    except ImportError as e:
      raise ImportError(
        'bybit sdk is not installed. Please install it with `pip install tribulnation-bybit`.'
      ) from e
    return BybitWallet.new(
      account.resolved_api_key,
      account.resolved_api_secret,
      settings={'validate': account.validate},
    )

  def bit2me(self, account: Bit2Me) -> Wallet:
    try:
      from tribulnation.bit2me import Wallet as Bit2MeWallet
    except ImportError as e:
      raise ImportError(
        'bit2me sdk is not installed. Please install it with `pip install tribulnation-bit2me`.'
      ) from e
    return Bit2MeWallet.new(
      account.resolved_api_key,
      account.resolved_api_secret,
      validate=account.validate,
    )

  def kraken(self, account: Kraken) -> Wallet:
    try:
      from tribulnation.kraken import Wallet as KrakenWallet
    except ImportError as e:
      raise ImportError(
        'kraken sdk is not installed. Please install it with `pip install tribulnation-kraken`.'
      ) from e
    return KrakenWallet.new(
      account.resolved_api_key,
      account.resolved_private_key,
      public=account.public,
      validate=account.validate,
    )

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
      case 'bybit':
        return self.bybit(account)
      case 'bit2me':
        return self.bit2me(account)
      case 'kraken':
        return self.kraken(account)
      case _:
        raise ValueError(f'Unsupported venue: {account.venue}')

  def venues(self) -> list[str]:
    return list(self.all_accounts)
