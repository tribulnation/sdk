from typing_extensions import Mapping, Sequence
from dataclasses import dataclass, field

from tribulnation.sdk.market import TradingMarkets, TradingVenue
from .accounts import Account, Dydx, Hyperliquid, Mexc

DEFAULT_ACCOUNTS: Mapping[str, Account] = {
  'dydx': Dydx(),
  'hyperliquid': Hyperliquid(),
  'mexc': Mexc()
}

@dataclass(frozen=True)
class MarketSDK(TradingMarkets):
  accounts: Mapping[str, Account] = field(default_factory=dict)

  @property
  def all_accounts(self) -> Mapping[str, Account]:
    return {**DEFAULT_ACCOUNTS, **self.accounts}

  def dydx(self, account: Dydx) -> TradingVenue:
    try:
      from tribulnation.dydx import DydxMarket
    except ImportError as e:
      raise ImportError('dydx market is not installed. Please install it with `pip install tribulnation-dydx`.') from e
    return DydxMarket.new(account.resolved_mnemonic, mainnet=account.venue == 'dydx', parent_subaccount=account.parent_subaccount)

  def hyperliquid(self, account: Hyperliquid) -> TradingVenue:
    try:
      from tribulnation.hyperliquid import HyperliquidMarket
    except ImportError as e:
      raise ImportError('hyperliquid market is not installed. Please install it with `pip install tribulnation-hyperliquid`.') from e
    return HyperliquidMarket.http(account.resolved_address, wallet=account.resolved_private_key, mainnet=account.venue == 'hyperliquid')

  def mexc(self, account: Mexc) -> TradingVenue:
    try:
      from tribulnation.mexc import MexcMarket
    except ImportError as e:
      raise ImportError('mexc market is not installed. Please install it with `pip install tribulnation-mexc`.') from e
    return MexcMarket.new(api_key=account.resolved_api_key, api_secret=account.resolved_api_secret, validate=account.validate)

  async def venue(self, id: str, /) -> TradingVenue:
    if (account := self.all_accounts.get(id)) is None:
      raise ValueError(f'No account found for venue id: {id}')
    match account.venue:
      case 'dydx' | 'dydx_testnet':
        return self.dydx(account)
      case 'hyperliquid' | 'hyperliquid_testnet':
        return self.hyperliquid(account)
      case 'mexc':
        return self.mexc(account)
      case _:
        raise ValueError(f'Unsupported venue: {account.venue}')

  async def venues(self) -> Sequence[str]:
    return list(self.all_accounts)
