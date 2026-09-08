from typing_extensions import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tribulnation.sdk.earn import Earn
from .accounts import (
  Account,
  Bybit,
  Coinbase,
  Kraken,
  Mexc,
  Bitget,
  Binance,
  Bit2Me,
  load_accounts,
)

DEFAULT_ACCOUNTS: Mapping[str, Account] = {
  'mexc': Mexc(public=True),
  'bit2me': Bit2Me(public=True),
}


@dataclass
class EarnSDK:
  accounts: Mapping[str, Account] = field(default_factory=dict[str, Account])

  @property
  def all_accounts(self) -> Mapping[str, Account]:
    return {**DEFAULT_ACCOUNTS, **self.accounts}

  @classmethod
  def load(cls, path: Path | str = 'sdk.toml') -> 'EarnSDK':
    """Construct an `EarnSDK` from a TOML file's `[accounts.<id>]` tables.

    Args:
      path: Path to a TOML file with an `[accounts]` table.
    """
    return cls(accounts=load_accounts(path))

  def binance(self, account: Binance) -> Earn:
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
    ).earn

  def bitget(self, account: Bitget) -> Earn:
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
    ).earn

  def mexc(self, account: Mexc) -> Earn:
    try:
      from tribulnation.mexc.earn import Earn as MexcEarn
    except ImportError as e:
      raise ImportError(
        'mexc sdk is not installed. Please install it with `pip install tribulnation-mexc`.'
      ) from e
    return MexcEarn()

  def bit2me(self, account: Bit2Me) -> Earn:
    try:
      from tribulnation.bit2me.earn import Earn as Bit2MeEarn
    except ImportError as e:
      raise ImportError(
        'bit2me sdk is not installed. Please install it with `pip install tribulnation-bit2me`.'
      ) from e
    return Bit2MeEarn.new(
      api_key=account.resolved_api_key,
      api_secret=account.resolved_api_secret,
      validate=account.validate,
    )

  def coinbase(self, account: Coinbase) -> Earn:
    try:
      from tribulnation.coinbase import Earn as CoinbaseEarn
    except ImportError as e:
      raise ImportError(
        'coinbase sdk is not installed. Please install it with `pip install tribulnation-coinbase`.'
      ) from e
    return CoinbaseEarn.new(account.resolved_key_name, account.resolved_private_key)

  def kraken(self, account: Kraken) -> Earn:
    try:
      from tribulnation.kraken import Earn as KrakenEarn
    except ImportError as e:
      raise ImportError(
        'kraken sdk is not installed. Please install it with `pip install tribulnation-kraken`.'
      ) from e
    return KrakenEarn.new(
      account.resolved_api_key,
      account.resolved_private_key,
      public=account.public,
      validate=account.validate,
    )

  def bybit(self, account: Bybit) -> Earn:
    try:
      from tribulnation.bybit import Earn as BybitEarn
    except ImportError as e:
      raise ImportError(
        'bybit sdk is not installed. Please install it with `pip install tribulnation-bybit`.'
      ) from e
    return BybitEarn.new(
      account.resolved_api_key,
      account.resolved_api_secret,
      settings={'validate': account.validate},
    )

  @property
  def all(self) -> dict[str, Earn]:
    out: dict[str, Earn] = {}
    for id, account in self.all_accounts.items():
      try:
        out[id] = self.venue(id)
      except NotImplementedError:
        ...
    return out

  def venue(self, id: str, /) -> Earn:
    if (account := self.all_accounts.get(id)) is None:
      raise ValueError(f'No account found for venue id: {id}')
    match account.venue:
      case 'binance':
        return self.binance(account)
      case 'bitget':
        return self.bitget(account)
      case 'mexc':
        return self.mexc(account)
      case 'bit2me':
        return self.bit2me(account)
      case 'coinbase':
        return self.coinbase(account)
      case 'bybit':
        return self.bybit(account)
      case 'kraken':
        return self.kraken(account)
      case _:
        raise NotImplementedError(f'Unsupported venue: {account.venue}')

  def venues(self) -> list[str]:
    return list(self.all_accounts)
