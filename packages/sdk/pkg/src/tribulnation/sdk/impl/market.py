from typing_extensions import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tribulnation.sdk.market import TradingMarkets, TradingVenue
from .accounts import Account, Binance, Dydx, Hyperliquid, Mexc, load_accounts

DEFAULT_ACCOUNTS: Mapping[str, Account] = {
  'dydx': Dydx(public=True),
  'hyperliquid': Hyperliquid(public=True),
  'mexc': Mexc(public=True),
  'binance': Binance(public=True),
}


@dataclass(frozen=True)
class MarketSDK(TradingMarkets):
  accounts: Mapping[str, Account] = field(default_factory=dict)

  @property
  def all_accounts(self) -> Mapping[str, Account]:
    return {**DEFAULT_ACCOUNTS, **self.accounts}

  @classmethod
  def load(cls, path: Path | str = 'sdk.toml') -> 'MarketSDK':
    """Construct a `MarketSDK` from a TOML file's `[accounts.<id>]` tables.

    Args:
      path: Path to a TOML file with an `[accounts]` table.
    """
    return cls(accounts=load_accounts(path))

  def dydx(self, account: Dydx) -> TradingVenue:
    try:
      from tribulnation.dydx import DydxMarket
    except ImportError as e:
      raise ImportError(
        'dydx market is not installed. Please install it with `pip install tribulnation-dydx`.'
      ) from e
    return DydxMarket.new(
      account.resolved_mnemonic,
      address=account.resolved_address,
      mainnet=account.venue == 'dydx',
      parent_subaccount=account.parent_subaccount,
    )

  def hyperliquid(self, account: Hyperliquid) -> TradingVenue:
    try:
      from tribulnation.hyperliquid import HyperliquidMarket
    except ImportError as e:
      raise ImportError(
        'hyperliquid market is not installed. Please install it with `pip install tribulnation-hyperliquid`.'
      ) from e
    return HyperliquidMarket.http(
      account.resolved_address,
      wallet=account.resolved_private_key,
      mainnet=account.venue == 'hyperliquid',
    )

  def mexc(self, account: Mexc) -> TradingVenue:
    try:
      from tribulnation.mexc import MexcMarket
    except ImportError as e:
      raise ImportError(
        'mexc market is not installed. Please install it with `pip install tribulnation-mexc`.'
      ) from e
    return MexcMarket.new(
      api_key=account.resolved_api_key,
      api_secret=account.resolved_api_secret,
      validate=account.validate,
    )

  def binance(self, account: Binance) -> TradingVenue:
    try:
      from tribulnation.binance import BinanceMarket
    except ImportError as e:
      raise ImportError(
        'binance market is not installed. Please install it with `pip install tribulnation-binance`.'
      ) from e
    return BinanceMarket.new(
      api_key=account.resolved_api_key,
      secret_key=account.resolved_secret_key,
      validate=account.validate,
    )

  def _venue(self, id: str, /) -> TradingVenue:
    if (account := self.all_accounts.get(id)) is None:
      raise ValueError(f'No account found for venue id: {id}')
    match account.venue:
      case 'dydx' | 'dydx_testnet':
        return self.dydx(account)
      case 'hyperliquid' | 'hyperliquid_testnet':
        return self.hyperliquid(account)
      case 'mexc':
        return self.mexc(account)
      case 'binance':
        return self.binance(account)
      case _:
        raise ValueError(f'Unsupported venue: {account.venue}')

  async def venue(self, id: str, /) -> TradingVenue:
    return self._venue(id)

  async def venues(self) -> Sequence[str]:
    return list(self.all_accounts)

  @property
  def all(self) -> dict[str, TradingVenue]:
    return {id: self._venue(id) for id in self.all_accounts}
