from typing_extensions import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tribulnation.sdk.market import TradingMarkets, TradingVenue
from .ownership import VenueOwner
from .accounts import (
  Account,
  Aster,
  Binance,
  Bit2Me,
  Bitget,
  Bybit,
  Coinbase,
  Deribit,
  Dydx,
  Hyperliquid,
  Kraken,
  Kucoin,
  Lighter,
  Mexc,
  load_accounts,
)


@dataclass(frozen=True)
class MarketSDK(TradingMarkets, VenueOwner[TradingVenue]):
  accounts: Mapping[str, Account] = field(default_factory=dict[str, Account])

  @classmethod
  def load(cls, path: Path | str = 'sdk.toml') -> 'MarketSDK':
    """Construct a `MarketSDK` from a TOML file's `[accounts.<id>]` tables.

    Args:
      path: Path to a TOML file with an `[accounts]` table.
    """
    return cls(accounts=load_accounts(path))

  def aster(self, account: Aster, id: str) -> TradingVenue:
    try:
      from tribulnation.aster import AsterMarket
    except ImportError as e:
      raise ImportError(
        'aster market is not installed. Please install it with `pip install tribulnation-aster`.'
      ) from e
    user, signer = account.resolved_user, account.resolved_signer
    return AsterMarket.new(
      user=user,
      signer=signer,
      public=account.public and user is None and signer is None,
      mainnet=account.venue == 'aster',
      validate=account.validate,
      account_id=id,
    )

  def dydx(self, account: Dydx, id: str) -> TradingVenue:
    try:
      from tribulnation.dydx import DydxMarket
    except ImportError as e:
      raise ImportError(
        'dydx market is not installed. Please install it with `pip install tribulnation-dydx`.'
      ) from e
    return DydxMarket.new(
      **account.resolved_creds,
      public=account.public,
      address=account.resolved_address,
      mainnet=account.venue == 'dydx',
      parent_subaccount=account.parent_subaccount,
      account_id=id,
    )

  def hyperliquid(self, account: Hyperliquid, id: str) -> TradingVenue:
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
      account_id=id,
    )

  def mexc(self, account: Mexc, id: str) -> TradingVenue:
    try:
      from tribulnation.mexc import MexcMarket
    except ImportError as e:
      raise ImportError(
        'mexc market is not installed. Please install it with `pip install tribulnation-mexc`.'
      ) from e
    api_key, api_secret = account.resolved_api_key, account.resolved_api_secret
    if account.public and api_key is None and api_secret is None:
      return MexcMarket.public(validate=account.validate, account_id=id)
    return MexcMarket.new(
      api_key=api_key,
      api_secret=api_secret,
      validate=account.validate,
      account_id=id,
    )

  def binance(self, account: Binance, id: str) -> TradingVenue:
    try:
      from tribulnation.binance import BinanceMarket
    except ImportError as e:
      raise ImportError(
        'binance market is not installed. Please install it with `pip install tribulnation-binance`.'
      ) from e
    api_key, secret_key = account.resolved_api_key, account.resolved_secret_key
    return BinanceMarket.new(
      api_key=api_key,
      secret_key=secret_key,
      public=account.public and api_key is None and secret_key is None,
      validate=account.validate,
      account_id=id,
    )

  def coinbase(self, account: Coinbase, id: str) -> TradingVenue:
    try:
      from tribulnation.coinbase import CoinbaseMarket
    except ImportError as e:
      raise ImportError(
        'coinbase market is not installed. Please install it with `pip install tribulnation-coinbase`.'
      ) from e
    key_name, private_key = account.resolved_key_name, account.resolved_private_key
    return CoinbaseMarket.new(
      key_name,
      private_key,
      public=account.public and key_name is None and private_key is None,
      account_id=id,
    )

  def bybit(self, account: Bybit, id: str) -> TradingVenue:
    try:
      from tribulnation.bybit import BybitMarket
    except ImportError as e:
      raise ImportError(
        'bybit market is not installed. Please install it with `pip install tribulnation-bybit`.'
      ) from e
    api_key, api_secret = account.resolved_api_key, account.resolved_api_secret
    return BybitMarket.new(
      api_key,
      api_secret,
      public=account.public and api_key is None and api_secret is None,
      settings={'validate': account.validate},
      account_id=id,
    )

  def bitget(self, account: Bitget, id: str) -> TradingVenue:
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
      account_id=id,
    )

  def bit2me(self, account: Bit2Me, id: str) -> TradingVenue:
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
      account_id=id,
    )

  def kraken(self, account: Kraken, id: str) -> TradingVenue:
    try:
      from tribulnation.kraken import KrakenMarket
    except ImportError as e:
      raise ImportError(
        'kraken market is not installed. Please install it with `pip install tribulnation-kraken`.'
      ) from e
    return KrakenMarket.new(
      account.resolved_api_key,
      account.resolved_private_key,
      public=account.public,
      validate=account.validate,
      account_id=id,
    )

  def kucoin(self, account: Kucoin, id: str) -> TradingVenue:
    """Build KuCoin's credential-free public Market surface."""
    try:
      from tribulnation.kucoin import KucoinMarket
    except ImportError as e:
      raise ImportError('Install tribulnation-kucoin to use this venue.') from e
    return KucoinMarket.new(validate=account.validate, account_id=id)

  def deribit(self, account: Deribit, id: str) -> TradingVenue:
    """Build Deribit's credential-free mainnet public Market surface."""
    if account.venue != 'deribit':
      raise ValueError('Deribit Market is qualified on mainnet only')
    try:
      from tribulnation.deribit import DeribitMarket
    except ImportError as e:
      raise ImportError('Install tribulnation-deribit to use this venue.') from e
    return DeribitMarket.new(validate=account.validate, account_id=id)

  def lighter(self, account: Lighter, id: str) -> TradingVenue:
    """Build Lighter's perpetual and spot Market surface on one account: API key,
    read-only auth token, or public (account reads from `account_index`/`address`)."""
    try:
      from tribulnation.lighter import LighterMarket
    except ImportError as e:
      raise ImportError(
        'lighter market is not installed. Please install it with `pip install tribulnation-lighter`.'
      ) from e
    api_private_key = account.resolved_api_private_key
    auth_token = account.resolved_auth_token
    return LighterMarket.new(
      account.resolved_account_index,
      account.resolved_api_key_index,
      api_private_key,
      auth_token=auth_token,
      address=account.resolved_address,
      network='mainnet' if account.venue == 'lighter' else 'testnet',
      public=account.public and api_private_key is None and auth_token is None,
      validate=account.validate,
      account_id=id,
    )

  def _venue(self, id: str, /) -> TradingVenue:
    if (account := self.accounts.get(id)) is None:
      raise ValueError(f'No account found for venue id: {id}')
    match account.venue:
      case 'aster' | 'aster_testnet':
        return self.aster(account, id)
      case 'dydx' | 'dydx_testnet':
        return self.dydx(account, id)
      case 'hyperliquid' | 'hyperliquid_testnet':
        return self.hyperliquid(account, id)
      case 'mexc':
        return self.mexc(account, id)
      case 'binance':
        return self.binance(account, id)
      case 'coinbase':
        return self.coinbase(account, id)
      case 'bybit':
        return self.bybit(account, id)
      case 'bit2me':
        return self.bit2me(account, id)
      case 'bitget':
        return self.bitget(account, id)
      case 'kraken':
        return self.kraken(account, id)
      case 'kucoin':
        return self.kucoin(account, id)
      case 'deribit' | 'deribit_testnet':
        return self.deribit(account, id)
      case 'lighter' | 'lighter_testnet':
        return self.lighter(account, id)
      case _:
        raise ValueError(f'Unsupported venue: {account.venue}')

  async def venue(self, id: str, /) -> TradingVenue:
    """Borrow a cached venue inside an entered root, otherwise construct a fresh one.

    The venue is built with `account_id=id`, so it and the exchanges and markets it
    creates report IDs that round-trip through this SDK.
    """
    return await self.venue_registry.get(id, lambda: self._venue(id))

  async def venues(self) -> Sequence[str]:
    return list(self.accounts)

  @property
  def all(self) -> dict[str, TradingVenue]:
    """Construct caller-managed venues outside a root context, or return live ones.

    Inside an entered root, first acquire any new venue with `await venue(id)`;
    synchronous construction cannot acquire its async resources.
    """
    return {
      id: self.venue_registry.unmanaged(id, lambda: self._venue(id))
      for id in self.accounts
    }
