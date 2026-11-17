"""The perpetual and spot exchanges: discovery, bulk snapshots, exchange-wide history,
the cross bucket and spot balances."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from typing_extensions import AsyncIterable, Collection, Mapping, Sequence, overload
from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.market import (
  Balance,
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  PerpCollateral,
  PerpExchange,
  PerpStats,
  Settings,
  SpotExchange,
  Ticker,
  Trade,
)

from ..core import ProductType
from . import account, history, stats
from .common import Public
from .markets import NadoPerpMarket, NadoSpotMarket


@dataclass(frozen=True, kw_only=True)
class Exchange(Public):
  """What both exchanges share: product discovery and exchange-wide fills."""

  @property
  def product_type(self) -> ProductType:
    """The type of product this exchange lists."""
    raise NotImplementedError

  async def product_ids(self) -> list[int]:
    """The product ids of every product of this exchange's type."""
    await self.shared.load_symbols()
    return [
      s['product_id']
      for s in self.shared.symbols.values()
      if s['type'] == self.product_type
    ]

  async def exchange_trades(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[ExchangeTrade]]:
    """Personal fills of every product of this type, each with its symbol."""
    async for page in history.exchange_trades(
      self.shared, await self.product_ids(), start, end
    ):
      yield page


@dataclass(frozen=True, kw_only=True)
class NadoSpotExchange(Exchange, SpotExchange):
  """Every spot product, traded against USDT0 on the subaccount's balances."""

  @property
  def product_type(self) -> ProductType:
    """Spot products."""
    return 'spot'

  @property
  def exchange_id(self) -> str:
    """The spot exchange."""
    return 'spot'

  async def markets(self) -> Sequence[str]:
    """Every spot product's symbol, untradable ones included (`rules().api` says
    whether it trades)."""
    return await self.shared.listed('spot')

  async def market(self, market_id: str, /) -> NadoSpotMarket:
    """A spot product by symbol."""
    s = await self.shared.symbol(market_id, type='spot')
    return NadoSpotMarket(
      shared=self.shared, symbol=market_id, product_id=s['product_id']
    )

  async def balance(self, asset: str, /, *, ttl: timedelta | None = None) -> Balance:
    """One spot asset's balance by asset id (`USDT0`, `KBTC`), zero when not held."""
    return await account.balance(self.shared, asset, ttl=ttl)

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, Ticker]:
    """Last price, 24h volumes and best bid/ask of every spot product, in two
    requests."""
    return await stats.tickers(self.shared, markets, type='spot')

  @overload
  def trades_history(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeTrade]: ...
  @overload
  def trades_history(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[Trade]: ...
  @PaginatedResponse.lift
  async def trades_history(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Personal spot fills, of one market or every market."""
    if market_id is None:
      async for page in self.exchange_trades(start, end):
        yield page
    else:
      async for page in (await self.market(market_id)).trades_history(start, end):
        yield page


@dataclass(frozen=True, kw_only=True)
class NadoPerpExchange(Exchange, PerpExchange):
  """Every USDT0-settled perpetual, on the subaccount's unified cross margin."""

  @property
  def product_type(self) -> ProductType:
    """Perpetual products."""
    return 'perp'

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """Every perpetual's symbol, untradable ones included (`rules().api` says whether
    it trades)."""
    return await self.shared.listed('perp')

  async def market(self, market_id: str, /) -> NadoPerpMarket:
    """A perpetual by symbol."""
    s = await self.shared.symbol(market_id, type='perp')
    return NadoPerpMarket(
      shared=self.shared, symbol=market_id, product_id=s['product_id']
    )

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, Ticker]:
    """Last price, 24h volumes and best bid/ask of every perpetual, in two requests."""
    return await stats.tickers(self.shared, markets, type='perp')

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, PerpStats]:
    """Index, mark, the next hourly settlement's predicted funding and base-unit open
    interest, in three requests."""
    return await stats.perp_stats(self.shared, markets)

  @overload
  def trades_history(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeTrade]: ...
  @overload
  def trades_history(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[Trade]: ...
  @PaginatedResponse.lift
  async def trades_history(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Personal perpetual fills, of one market or every market."""
    if market_id is None:
      async for page in self.exchange_trades(start, end):
        yield page
    else:
      async for page in (await self.market(market_id)).trades_history(start, end):
        yield page

  @overload
  def funding_payments(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeFundingPayment]: ...
  @overload
  def funding_payments(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]: ...
  @PaginatedResponse.lift
  async def funding_payments(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[FundingPayment]]:
    """Personal funding payments, of one market or every market, received-positive."""
    if market_id is None:
      async for page in history.exchange_funding_payments(
        self.shared, await self.product_ids(), start, end
      ):
        yield page
    else:
      async for page in (await self.market(market_id)).funding_payments(start, end):
        yield page

  async def perp_collateral(
    self, market_id: str | None = None, /, *, ttl: timedelta | None = None
  ) -> PerpCollateral:
    """The cross bucket (the whole subaccount), or the bucket backing a market."""
    if market_id is not None:
      return await (await self.market(market_id)).perp_collateral(ttl=ttl)
    return account.cross_bucket(await account.summary(self.shared, ttl=ttl))
