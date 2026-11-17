"""The perpetual exchange: discovery, bulk snapshots and exchange-wide history."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from typing_extensions import AsyncIterable, Collection, Mapping, Sequence, overload
from typed_risex.markets.all import MarketInfo
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

from ..core import FUNDING_INTERVAL, listed, market_index
from . import account, history
from .common import Public
from .markets import RisexPerpMarket


def selected(
  markets: Collection[str] | None, rows: Mapping[int, MarketInfo]
) -> list[str]:
  """The listed markets among `markets`, or every listed one."""
  ids = [str(i) for i, m in rows.items() if listed(m)]
  if markets is None:
    return ids
  wanted = set(markets)
  return [m for m in ids if m in wanted]


def ticker(row: MarketInfo) -> Ticker:
  """Last price and 24h quote volume: the venue publishes no best bid/ask in its
  market data, nor a base volume."""
  return Ticker(last=row['last_price'], quote_volume_24h=row['quote_volume_24h'])


@dataclass(frozen=True, kw_only=True)
class RisexPerpExchange(Public, PerpExchange):
  """Every perpetual market, backed by the account's one cross-margin bucket."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """Every listed market (`active` and unlocked), by `market_id`."""
    rows = await self.shared.load_markets()
    return [str(i) for i, m in rows.items() if listed(m)]

  async def market(self, market_id: str, /) -> RisexPerpMarket:
    """A market by `market_id`, unlisted ones included."""
    row = await self.shared.market(market_index(market_id))
    return RisexPerpMarket(shared=self.shared, index_id=row['market_id'])

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, Ticker]:
    """Tickers of the listed markets, from one refreshed `markets.all` read."""
    if markets is not None and not markets:
      return {}
    rows = await self.shared.load_markets(refetch=True)
    return {m: ticker(rows[int(m)]) for m in selected(markets, rows)}

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, PerpStats]:
    """Index, mark and open interest (base units) from one refreshed `markets.all`
    read, and the funding estimate from one `expected_funding_rate` frame.

    The open interest's unit is undocumented: BTC's `250.8` beside a 24h volume of
    39.4M USDC (mainnet, 2026-11-17) reads as BTC, not USDC.
    """
    if markets is not None and not markets:
      return {}
    rows = await self.shared.load_markets(refetch=True)
    wanted = selected(markets, rows)
    if not wanted:
      return {}
    funding = await self.shared.call(
      lambda: history.expected_funding(self.shared, [int(m) for m in wanted])
    )
    stats: dict[str, PerpStats] = {}
    for m in wanted:
      row = rows[int(m)]
      estimate = funding.get(int(m))
      stats[m] = PerpStats(
        index=row['index_price'],
        mark=row['mark_price'],
        funding=estimate['estimated_rate'] if estimate else None,
        next_funding_time=estimate['next_funding_time'] if estimate else None,
        funding_interval=FUNDING_INTERVAL,
        open_interest=row['open_interest'],
      )
    return stats

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
    """The account's fills, of one market or every market, newest first."""
    index = None if market_id is None else market_index(market_id)
    async for page in history.trades_history(self.shared, index, start, end):
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
    """The account's hourly funding, positive when received, of one market or every
    market."""
    index = None if market_id is None else market_index(market_id)
    async for page in history.funding_payments(self.shared, index, start, end):
      yield page

  async def perp_collateral(
    self, market_id: str | None = None, /, *, ttl: timedelta | None = None
  ) -> PerpCollateral:
    """The account's one cross bucket, whatever the market."""
    if market_id is not None:
      await self.shared.market(market_index(market_id))
    return await account.collateral(self.shared, ttl=ttl)
