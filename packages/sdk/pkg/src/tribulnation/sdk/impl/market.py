from typing_extensions import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tribulnation.sdk.market import TradingMarkets, TradingVenue
from .accounts import (
  Account,
  Binance,
  Bit2Me,
  Bitget,
  Bybit,
  Coinbase,
  Dydx,
  Hyperliquid,
  Mexc,
  load_accounts,
)

DEFAULT_ACCOUNTS: Mapping[str, Account] = {
  'dydx': Dydx(public=True),
  'hyperliquid': Hyperliquid(public=True),
  'mexc': Mexc(public=True),
  'binance': Binance(public=True),
  'bit2me': Bit2Me(public=True),
  'bitget': Bitget(public=True),
}


@dataclass(frozen=True)
class MarketSDK(TradingMarkets):
  accounts: Mapping[str, Account] = field(default_factory=dict[str, Account])

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

  def coinbase(self, account: Coinbase) -> TradingVenue:
    try:
      from tribulnation.coinbase import CoinbaseMarket
    except ImportError as e:
      raise ImportError(
        'coinbase market is not installed. Please install it with `pip install tribulnation-coinbase`.'
      ) from e
    return CoinbaseMarket.new(account.resolved_key_name, account.resolved_private_key)

  def bybit(self, account: Bybit) -> TradingVenue:
    try:
      from tribulnation.bybit import BybitMarket
    except ImportError as e:
      raise ImportError(
        'bybit market is not installed. Please install it with `pip install tribulnation-bybit`.'
      ) from e
    return BybitMarket.new(
      account.resolved_api_key,
      account.resolved_api_secret,
      settings={'validate': account.validate},
    )

  def bitget(self, account: Bitget) -> TradingVenue:
    try:
      from tribulnation.bitget import BitgetMarket
    except ImportError as e:
      raise ImportError(
        'bitget market is not installed. Please install it with `pip install tribulnation-bitget`.'
      ) from e
    return BitgetMarket.new(
      account.resolved_access_key,
      account.resolved_secret_key,
      account.resolved_passphrase,
      uta=account.uta,
      public=account.public,
      validate=account.validate,
    )

  def bit2me(self, account: Bit2Me) -> TradingVenue:
    try:
      from tribulnation.bit2me import Bit2MeMarket
    except ImportError as e:
      raise ImportError(
        'bit2me market is not installed. Please install it with `pip install tribulnation-bit2me`.'
      ) from e
    return Bit2MeMarket.new(
      account.resolved_api_key,
      account.resolved_api_secret,
      public=account.public,
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
      case 'coinbase':
        return self.coinbase(account)
      case 'bybit':
        return self.bybit(account)
      case 'bit2me':
        return self.bit2me(account)
      case 'bitget':
        return self.bitget(account)
      case _:
        raise ValueError(f'Unsupported venue: {account.venue}')

  async def venue(self, id: str, /) -> TradingVenue:
    return self._venue(id)

  async def venues(self) -> Sequence[str]:
    return list(self.all_accounts)

  @property
  def all(self) -> dict[str, TradingVenue]:
    return {id: self._venue(id) for id in self.all_accounts}
