from typing_extensions import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tribulnation.sdk.earn import Earn
from .accounts import Account, Mexc, Bitget, Binance, load_accounts

DEFAULT_ACCOUNTS: Mapping[str, Account] = {
  'mexc': Mexc(public=True),
}


@dataclass
class EarnSDK:
  accounts: Mapping[str, Account] = field(default_factory=dict)

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
      case _:
        raise NotImplementedError(f'Unsupported venue: {account.venue}')

  def venues(self) -> list[str]:
    return list(self.all_accounts)
