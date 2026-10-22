"""The perpetual exchange: discovery, bulk snapshots and exchange-wide fills."""

from dataclasses import dataclass
from datetime import datetime

from typing_extensions import AsyncIterable, Collection, Mapping, Sequence, overload
from typed_extended.info.markets import Market as MarketRow
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

from ..core import FUNDING_INTERVAL
from . import account, history
from .common import Public, listed_perps, price_or_none
from .markets import ExtendedPerpMarket


def selected(
  markets: Collection[str] | None, rows: Mapping[str, MarketRow]
) -> list[str]:
  """The listed perpetuals among `markets`, or every one of them."""
  listed = listed_perps(rows)
  if markets is None:
    return listed
  wanted = set(markets)
  return [m for m in listed if m in wanted]


def ticker(row: MarketRow) -> Ticker:
  """Last, best bid and ask, and 24h volumes in base and collateral units; a `0` price
  is the venue's "none", and best-level sizes are not published."""
  stats = row['marketStats']
  return Ticker(
    last=price_or_none(stats['lastPrice']),
    bid=price_or_none(stats['bidPrice']),
    ask=price_or_none(stats['askPrice']),
    base_volume_24h=stats['dailyVolumeBase'],
    quote_volume_24h=stats['dailyVolume'],
  )


def perp_stats(row: MarketRow) -> PerpStats:
  """Index, mark, the funding estimate and its time, and base-unit open interest."""
  stats = row['marketStats']
  return PerpStats(
    index=stats['indexPrice'],
    mark=stats['markPrice'],
    funding=stats['fundingRate'],
    next_funding_time=stats['nextFundingRate'],
    funding_interval=FUNDING_INTERVAL,
    open_interest=stats['openInterestBase'],
  )


@dataclass(frozen=True, kw_only=True)
class ExtendedPerpExchange(Public, PerpExchange):
  """Every perpetual market, backed by the sub-account's one cross-margin bucket."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """Every listed perpetual (`ACTIVE`, `REDUCE_ONLY` or `PRELISTED`), by name;
    `rules().api` says which trade."""
    return listed_perps(await self.shared.load_markets())

  async def market(self, market_id: str, /) -> ExtendedPerpMarket:
    """A perpetual market by name, delisted ones included."""
    row = await self.shared.perp(market_id)
    return ExtendedPerpMarket(shared=self.shared, name=row['name'])

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Tickers of the listed perpetuals, from one `info.markets` read."""
    if markets is not None and not markets:
      return {}
    rows = await self.shared.load_markets(refetch=True)
    return {m: ticker(rows[m]) for m in selected(markets, rows)}

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Pricing and funding snapshots of the listed perpetuals, from one `info.markets`
    read."""
    if markets is not None and not markets:
      return {}
    rows = await self.shared.load_markets(refetch=True)
    return {m: perp_stats(rows[m]) for m in selected(markets, rows)}

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
    """Funding payments, positive when received, of one market or every perpetual
    (delisted included)."""
    if market_id is not None:
      await self.shared.perp(market_id)
    async for page in history.funding_payments(self.shared, market_id, start, end):
      yield page

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """The sub-account's one cross bucket, whatever the market."""
    if market_id is not None:
      await self.shared.perp(market_id)
    return account.bucket(await self.shared.call(self.shared.client.account.balance))
