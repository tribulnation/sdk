"""Bitget perpetual markets, addressed by product line and native symbol."""

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket as _PerpMarket,
  PerpPosition,
  Rules,
  Settings,
  Trade,
)

from .impl import (
  CANDLE_INTERVALS,
  PERP,
  MarketMixin,
  classic_mix_account,
  depth_stream,
  perp_candles,
  funding_rates,
  open_orders,
  parse_book,
  parse_perp_rules,
  perp_depth_limit,
  perp_position,
  trades_history,
  trades_stream,
  uta_perp_collateral,
)
from .impl.account import not_supported_classic_collateral
from .impl.parse import PerpProduct, perp_exchange_id


@dataclass(kw_only=True, frozen=True)
class PerpMarket(MarketMixin, _PerpMarket):
  """One Bitget perpetual contract; USDC and coin products are public-data only."""

  perp_product: PerpProduct = PERP

  CANDLE_INTERVALS = CANDLE_INTERVALS

  @property
  def product(self) -> PerpProduct:
    return self.perp_product

  @property
  def market_id(self) -> str:
    return self.symbol

  @property
  def exchange_id(self) -> str:
    return perp_exchange_id(self.product)

  @property
  def venue_id(self) -> str:
    return 'bitget'

  async def depth(self, *, levels: int | None = None) -> Book:
    """Fetch the market order book (100 levels a side when `levels` is omitted).

    The futures book takes a fixed depth enum, so `levels` is served by the next
    member up and trimmed to size.
    """
    book = await self.call(
      lambda: self.client.classic.mix.market.orderbook(
        self.symbol,
        product_type=self.product,
        limit=perp_depth_limit(levels),
        validate=self.validate,
      )
    )
    parsed = parse_book(book['bids'], book['asks'])
    return parsed if levels is None else parsed.limit(levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the market order book."""
    return depth_stream(self, levels=levels, queue_size=queue_size, overflow=overflow)

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Fetch the market rules from the public contract catalogue.

    Args:
      refetch: Refetch the catalogue instead of reading the cached one.
    """
    contracts = await self.perp_contracts(self.product, refetch=refetch)
    return parse_perp_rules(contracts[self.symbol], product=self.product)

  def candles(
    self,
    interval: CandleInterval,
    start: datetime,
    end: datetime,
  ) -> PaginatedResponse[Candle]:
    """Fetch candles with opening timestamps in `[start, end)`, in native order."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(perp_candles(self, interval, start, end))

  async def open_orders(self) -> Sequence[OrderState]:
    """Fetch your currently open orders."""
    return await open_orders(self)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Fetch your trades history."""
    return PaginatedResponse(trades_history(self, start, end))

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades."""
    return trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def perp_position(self) -> PerpPosition:
    """Fetch your open position in the market."""
    self.require_account_surface()
    return await perp_position(self, self.symbol)

  async def perp_collateral(self) -> PerpCollateral:
    """Fetch the collateral bucket backing this market.

    A UTA account has one margin pool across every product line, reported with the
    margin mode configured for this symbol. A Classic account reports no margin
    requirement figures at all, so it raises `NotImplementedError`.
    """
    self.require_account_surface()
    if await self.is_uta():
      return await uta_perp_collateral(self, self.symbol)
    raise not_supported_classic_collateral()

  async def available_notional(self) -> Decimal:
    """Fetch the max. notional position you can open: free margin times max leverage.

    Classic reads the futures wallet's `available`; UTA the unified pool's effective
    equity.
    """
    self.require_account_surface()
    contracts = await self.perp_contracts(self.product)
    max_leverage = contracts[self.symbol]['maxLever']
    if await self.is_uta():
      collateral = await uta_perp_collateral(self, self.symbol)
      return collateral.free_collateral * max_leverage
    account = await classic_mix_account(self, self.symbol)
    return account['available'] * max_leverage

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Fetch the market index price."""
    prices = await self.call(
      lambda: self.client.classic.mix.market.symbol_price(
        self.symbol, product_type=self.product, validate=self.validate
      )
    )
    return prices[0]['indexPrice']

  async def next_funding(self) -> NextFunding:
    """Fetch the next funding rate, settlement time and interval.

    Read from the UTA v3 public funding-rate endpoint, which serves every account
    mode: its Classic v2 twin declares `minFundingRate`/`maxFundingRate` required,
    which the venue sends as `null` on 11 contracts.
    """
    rates = await self.call(
      lambda: self.client.uta.market.funding_rate.current(
        self.product, symbol=self.symbol, validate=self.validate
      )
    )
    rate = rates[0]
    return NextFunding(
      rate=rate['fundingRate'],
      time=rate['nextUpdate'],
      interval=timedelta(hours=rate['fundingRateInterval']),
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Fetch the market's historical funding rates, newest first."""
    return PaginatedResponse(funding_rates(self, start, end))

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Not supported: Bitget publishes no closed set of futures ledger types.

    Neither ledger that would carry the settlements filters on a documented value --
    `classic.mix.account.bills`' `businessType` and `classic.tax.futures_records`'
    `futureTaxType` on Classic, `uta.account.financial_records`' `type` on UTA are all
    free text the venue documents as open-ended -- so there is no funding-fee value to
    filter on without guessing.
    """
    raise NotImplementedError(
      'not supported: Bitget publishes no closed set of futures ledger types '
      '(`classic.mix.account.bills` `businessType`, `classic.tax.futures_records` '
      '`futureTaxType`, `uta.account.financial_records` `type`), so there is no '
      'documented funding-fee value to filter on'
    )

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Not implemented: Bitget is not a venue we trade on."""
    raise NotImplementedError('Trading is not implemented for Bitget.')

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Not implemented: Bitget is not a venue we trade on."""
    raise NotImplementedError('Trading is not implemented for Bitget.')
