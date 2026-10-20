"""The perpetual exchange: discovery, bulk snapshots and exchange-wide history."""

from dataclasses import dataclass
from datetime import datetime, timezone

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

from ..core import FUNDING_INTERVAL
from . import account, history
from .common import Public
from .markets import MarginTradePerpMarket, next_hour


@dataclass(frozen=True, kw_only=True)
class MarginTradePerpExchange(Public, PerpExchange):
  """Every perpetual market, backed by the account's cross margin."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """Every listed perpetual's coin name, delisted ones included (`rules().api` says
    whether it trades)."""
    await self.shared.load_universe()
    return list(self.shared.universe)

  async def market(self, market_id: str, /) -> MarginTradePerpMarket:
    """A perpetual market by coin name."""
    m = await self.shared.asset(market_id)
    return MarginTradePerpMarket(shared=self.shared, coin=m['name'])

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Not supported: the venue's market contexts carry no last trade or best bid/ask."""
    raise NotImplementedError(f'Margin Trade tickers are not implemented: {self.id}')

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Oracle (index), mark, the current hourly funding rate and open interest."""
    meta, contexts = await self.shared.call(self.shared.client.info.meta_and_asset_ctxs)
    now = datetime.now(timezone.utc)
    return {
      item['name']: PerpStats(
        index=ctx['oraclePx'],
        mark=ctx['markPx'],
        funding=ctx['funding'],
        next_funding_time=next_hour(now),
        funding_interval=FUNDING_INTERVAL,
        open_interest=ctx['openInterest'],
      )
      for item, ctx in zip(meta['universe'], contexts)
      if markets is None or item['name'] in markets
    }

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
    """Perpetual fills, of one market or every market."""
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
    """Funding payments, of one market or every market."""
    async for page in history.funding_payments(self.shared, market_id, start, end):
      yield page

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """The cross bucket, or the bucket backing a market."""
    if market_id is not None:
      return await (await self.market(market_id)).perp_collateral()
    else:
      state = await self.shared.call(
        lambda: self.shared.client.info.clearinghouse_state(self.shared.user)
      )
      return account.cross_collateral(state)
