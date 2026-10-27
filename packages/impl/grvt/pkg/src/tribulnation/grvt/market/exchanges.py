"""The perpetual exchange: discovery, bulk snapshots, exchange-wide history and the
cross collateral bucket."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from typing_extensions import AsyncIterable, Collection, Mapping, Sequence, overload
from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.market import (
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  PerpCollateral,
  PerpExchange,
  PerpStats,
  Settings,
  Ticker,
  Trade,
)

from . import account, history, stats
from .common import Public
from .markets import GrvtPerpMarket


@dataclass(frozen=True, kw_only=True)
class GrvtPerpExchange(Public, PerpExchange):
  """Every USDT-margined perpetual, backed by the trading sub-account's cross margin."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """Every perpetual's instrument name, delisted ones included (`rules().api` says
    whether it trades)."""
    return list(await self.shared.load_instruments())

  async def market(self, market_id: str, /) -> GrvtPerpMarket:
    """A perpetual by instrument name."""
    detail = await self.shared.instrument(market_id)
    return GrvtPerpMarket(shared=self.shared, instrument=detail['instrument'])

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, Ticker]:
    """One `ticker` per perpetual, concurrently: last price, best bid/ask with sizes
    and 24h volumes (taker buys plus sells)."""
    return await stats.tickers(self.shared, markets)

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, PerpStats]:
    """Index, mark, indicative funding and base-unit open interest, one `ticker` per
    perpetual."""
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
    """Personal perpetual fills, of one market or every market (delisted included)."""
    async for page in history.trades_history(self.shared, market_id, start, end):
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
    async for page in history.funding_payments(self.shared, market_id, start, end):
      yield page

  async def perp_collateral(
    self, market_id: str | None = None, /, *, ttl: timedelta | None = None
  ) -> PerpCollateral:
    """The cross bucket, or the bucket backing a market."""
    if market_id is not None:
      return await (await self.market(market_id)).perp_collateral(ttl=ttl)
    return account.cross_bucket(await account.summary(self.shared))
