"""Perpetual and spot exchanges: discovery, bulk snapshots and exchange-wide history."""

from dataclasses import dataclass
from datetime import datetime

from typing_extensions import AsyncIterable, Collection, Mapping, Sequence, overload
from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.market import (
  Exchange,
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

from ..core import parse_market_id
from . import account, history, stats
from .common import Public
from .markets import LighterPerpMarket, LighterSpotMarket


@dataclass(frozen=True, kw_only=True)
class LighterPerpExchange(Public, PerpExchange):
  """Every perpetual market, backed by the account's cross margin and isolated buckets."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """Every perpetual market id, inactive ones included (`rules().api` says whether
    it trades)."""
    await self.shared.load_details()
    return [str(m) for m in self.shared.perps]

  async def market(self, market_id: str, /) -> LighterPerpMarket:
    """A perpetual market by id."""
    detail = await self.shared.perp(parse_market_id(market_id))
    return LighterPerpMarket(shared=self.shared, market_index=detail['market_id'])

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Last price, best bid/ask and 24h volumes from one `market_stats:all` snapshot."""
    return await stats.perp_tickers(self.shared, markets)

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Index, mark, predicted funding and base-unit open interest."""
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
    index = None if market_id is None else parse_market_id(market_id)
    async for page in history.trades_history(
      self.shared, 'perp', index, start, end, fee=history.perp_fee
    ):
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
    """Personal funding payments, of one market or every market."""
    index = None if market_id is None else parse_market_id(market_id)
    async for page in history.funding_payments(self.shared, index, start, end):
      yield page

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """The cross bucket, or the bucket backing a market."""
    if market_id is not None:
      return await (await self.market(market_id)).perp_collateral()
    return account.cross_bucket(await self.shared.account())


@dataclass(frozen=True, kw_only=True)
class LighterSpotExchange(Public, Exchange):
  """Every spot market."""

  @property
  def exchange_id(self) -> str:
    """The spot exchange."""
    return 'spot'

  async def markets(self) -> Sequence[str]:
    """Every spot market id, inactive ones included."""
    await self.shared.load_details()
    return [str(m) for m in self.shared.spots]

  async def market(self, market_id: str, /) -> LighterSpotMarket:
    """A spot market by id."""
    detail = await self.shared.spot(parse_market_id(market_id))
    return LighterSpotMarket(
      shared=self.shared,
      market_index=detail['market_id'],
      base_asset=detail['base_asset_id'],
      quote_asset=detail['quote_asset_id'],
    )

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Last price, best bid/ask and 24h volumes from one `spot_market_stats:all` snapshot."""
    return await stats.spot_tickers(self.shared, markets)

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
    """Personal spot fills, of one market or every market, with fees in the received
    asset."""
    index = None if market_id is None else parse_market_id(market_id)
    await self.shared.load_details()
    spots = self.shared.spots
    fee = history.spot_fee(
      lambda m: spots[m]['base_asset_id'], lambda m: spots[m]['quote_asset_id']
    )
    async for page in history.trades_history(
      self.shared, 'spot', index, start, end, fee=fee
    ):
      yield page
