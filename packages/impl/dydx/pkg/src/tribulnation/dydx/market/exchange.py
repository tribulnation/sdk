from typing_extensions import AsyncIterable, Collection, Mapping, Sequence, overload
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from tribulnation.sdk import PerpExchange
from tribulnation.sdk.core import ApiError, PaginatedResponse
from tribulnation.sdk.market import (
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  PerpCollateral,
  PerpStats,
  Settings,
  Ticker,
  Trade,
)

from tribulnation.dydx.core import wrap_exceptions
from .impl import ExchangeMixin, effective_mmf, perp_stats, tickers
from .market import Market

# MIGRATION NOTE: the subaccount is no longer smuggled into the market id as a
# `<BASE>-USD:<N>` suffix. It now lives on the `Exchange` (one exchange == one
# subaccount == one margin/liquidation bucket), resolved from the exchange id via
# `venue.exchange('perp')` (parent subaccount) or `venue.exchange('perp.<N>')`
# (child subaccount `<N>`). Markets inherit the subaccount from their exchange, so
# every account-scoped method keys off the same bucket. The old suffix `parse_market_id`
# has been retired (grep-confirmed: no callers used the suffix form).


@dataclass(frozen=True)
class Exchange(ExchangeMixin, PerpExchange):
  subaccount: int = 0
  """The subaccount this exchange (margin bucket) addresses. Parent subaccounts are
  `< 128` (cross); child subaccounts are `128 + parent`, `256 + parent`, ... (isolated)."""

  @property
  def exchange_id(self) -> str:
    if self.subaccount == self.shared.parent_subaccount:
      return 'perp'
    return f'perp.{self.subaccount}'

  @property
  def venue_id(self) -> str:
    return 'dydx'

  async def markets(self):
    markets = await self.shared.load_markets()
    return list(markets)

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, PerpStats]:
    """Fetch pricing and funding stats for every perp market in one call.

    Args:
      markets: Market tickers to keep. `None` keeps every market.
      settings: Accepted for interface compatibility and ignored — dYdX reports
        no mark price, so there is no oracle-vs-mark choice to make.

    Returns:
      A mapping of market ticker to its `PerpStats`.
    """
    return await perp_stats(self, markets)

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    return await tickers(self, markets, settings=settings)

  async def market(self, market_id: str, /):
    """Fetch a market by ID.

    - `market_id`: `<BASE>-USD`

    The market inherits this exchange's `subaccount`.
    """
    markets = await self.shared.load_markets()
    return Market(
      shared=self.shared,
      perpetual_market=markets[market_id],
      subaccount=self.subaccount,
    )

  @overload
  def trades_history(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeTrade]:
    """Fetch all-market history."""
    ...

  @overload
  def trades_history(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[Trade]:
    """Fetch selected-market history."""
    ...

  @PaginatedResponse.lift
  @wrap_exceptions
  async def trades_history(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fetch all-market fills for this subaccount, or delegate a selected market."""
    if market_id is not None:
      async for page in super().trades_history(market_id, start, end):
        yield page
      return
    start, end = start.astimezone(), end.astimezone()
    paging = self.indexer.data.get_fills_paged(
      address=self.address,
      subaccount=self.subaccount,
      created_before_or_at=end,
      market_type='PERPETUAL',
    )
    async for fills in paging.via(self.call_dydx):
      trades = [
        ExchangeTrade(
          market_id=fill['market'],
          id=fill['id'],
          price=Decimal(fill['price']),
          qty=Decimal(fill['size']) * (1 if fill['side'] == 'BUY' else -1),
          time=fill['createdAt'],
          maker=fill['liquidity'] == 'MAKER',
          fee=Trade.Fee(asset='USDC', amount=Decimal(fill['fee'])),
          details=fill,
        )
        for fill in fills
        if start <= fill['createdAt'] <= end
      ]
      if trades:
        yield trades

  @overload
  def funding_payments(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeFundingPayment]:
    """Fetch all-market history."""
    ...

  @overload
  def funding_payments(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Fetch selected-market history."""
    ...

  @PaginatedResponse.lift
  @wrap_exceptions
  async def funding_payments(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[FundingPayment]]:
    """Fetch all-market funding for this subaccount, or delegate a selected market."""
    if market_id is not None:
      async for page in super().funding_payments(market_id, start, end):
        yield page
      return
    start, end = start.astimezone(), end.astimezone()
    paging = self.indexer.data.get_funding_payments_paged(
      address=self.address,
      subaccount=self.subaccount,
      after_or_at=start,
    )
    async for batch in paging.via(self.call_dydx):
      payments = [
        ExchangeFundingPayment(
          market_id=item['ticker'],
          amount=-Decimal(item['payment']),
          time=item['createdAt'],
        )
        for item in batch
        if start <= item['createdAt'] <= end
      ]
      if payments:
        yield payments

  @wrap_exceptions
  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """Fetch the perpetual collateral bucket for this exchange's subaccount.

    dYdX has one collateral pool per subaccount, so this exchange (margin bucket)
    is the source of truth for its collateral. Passing a `market_id` delegates to
    the market (which returns the same exchange-level bucket — dYdX has no per-market mode).
    """
    if market_id is not None:
      m = await self.market(market_id)
      return await m.perp_collateral()
    address = self.address
    sub, markets = await asyncio.gather(
      self.indexer.data.get_subaccount(address=address, subaccount=self.subaccount),
      self.shared.load_markets(),
    )
    account = sub['subaccount']
    equity = Decimal(account['equity'])
    free_collateral = Decimal(account['freeCollateral'])

    notional = Decimal(0)
    maintenance_margin = Decimal(0)
    for position in account['openPerpetualPositions'].values():
      market = markets[position['market']]
      price = market.get('oraclePrice')
      if price is None:
        raise ApiError(f'Oracle price unavailable for {position["market"]}')
      position_notional = abs(Decimal(position['size'])) * Decimal(price)
      notional += position_notional
      maintenance_margin += position_notional * effective_mmf(market)

    leverage = notional / equity if equity > 0 else Decimal(0)
    margin_mode = 'cross' if self.subaccount < 128 else 'isolated'

    return PerpCollateral(
      equity=equity,
      free_collateral=free_collateral,
      initial_margin=equity - free_collateral,
      maintenance_margin=maintenance_margin,
      leverage=leverage,
      margin_mode=margin_mode,
    )
