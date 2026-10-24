"""Spot and perpetual exchanges: discovery, bulk tickers, perpetual statistics and
exchange-wide history.

Per-market methods use the SDK's default delegation to `market(market_id)`.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing_extensions import AsyncIterable, Collection, Mapping, Sequence, overload
from typed_margin_trade.coingecko.derivatives.contracts import DerivativeContract
from typed_margin_trade.coingecko.spot.tickers import SpotTicker
from typed_margin_trade.schemas import Fill
from tribulnation.sdk.core import PaginatedResponse, SDK
from tribulnation.sdk.market import (
  Balance,
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  PerpCollateral,
  PerpExchange as SDKPerpExchange,
  PerpStats,
  Settings,
  SpotExchange as SDKSpotExchange,
  Ticker,
  Trade,
)
from ..core import FUNDING_INTERVAL, Public, parse_trade
from .collateral import cross_collateral, spot_balance
from .markets import PerpMarket, SpotMarket, next_settlement


def is_spot_fill(fill: Fill) -> bool:
  """Spot coins are pair names (`PEARL/USDC`); perpetual coins never contain a slash.

  Deciding by name, not by the listed markets, keeps delisted markets' fills.
  """
  return '/' in fill['coin']


def exchange_trade(fill: Fill) -> ExchangeTrade:
  """A fill with its native market ID."""
  trade = parse_trade(fill)
  return ExchangeTrade(**vars(trade), market_id=fill['coin'])


def quote_ticker(
  quote: DerivativeContract | SpotTicker | None,
  *,
  base_volume: Decimal,
  quote_volume: Decimal,
) -> Ticker:
  """A ticker with the context's 24h volumes and, when published, the CoinGecko
  feed's last trade and best bid/ask (it publishes no sizes)."""
  return Ticker(
    last=quote['last_price'] if quote else None,
    bid=quote.get('bid') if quote else None,
    ask=quote.get('ask') if quote else None,
    base_volume_24h=base_volume,
    quote_volume_24h=quote_volume,
  )


@dataclass(frozen=True, kw_only=True)
class SpotExchange(Public, SDKSpotExchange):
  """margin.trade spot: the spot wallet, separate from the perpetual one."""

  @property
  def exchange_id(self) -> str:
    """The spot exchange ID."""
    return 'spot'

  async def markets(self) -> Sequence[str]:
    """List the pair names."""
    return list(await self.shared.spot_pairs())

  async def market(self, market_id: str, /) -> SpotMarket:
    """Resolve a pair by name."""
    pairs = await self.shared.spot_pairs()
    if market_id not in pairs:
      raise ValueError(f'Unknown margin.trade spot pair: {market_id}')
    return SpotMarket(shared=self.shared, meta=pairs[market_id])

  async def balance(self, asset: str, /) -> Balance:
    """One spot token's balance by symbol (`USDC`, `PEARL`).

    Raises:
      ValueError: No listed pair trades the token.
    """
    pairs = await self.shared.spot_pairs()
    tokens = {t['name']: t['index'] for p in pairs.values() for t in (p.base, p.quote)}
    if asset not in tokens:
      raise ValueError(f'Unknown margin.trade spot token: {asset}')
    state = await self.shared.call(
      lambda: self.client.info.spot_clearinghouse_state(self.shared.address)
    )
    return spot_balance(state, tokens[asset])

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """24h volumes from the spot contexts; last and best bid/ask from CoinGecko."""
    pairs = await self.shared.spot_pairs()
    names = {(p.base['name'], p.quote['name']): name for name, p in pairs.items()}
    gecko = await self.shared.call(self.client.coingecko.spot.tickers)
    quotes = {
      names[key]: row
      for row in gecko
      if (key := (row['base_currency'], row['target_currency'])) in names
    }
    _, ctxs = await self.shared.call(self.client.info.spot_meta_and_asset_ctxs)
    return {
      ctx['coin']: quote_ticker(
        quotes.get(ctx['coin']),
        base_volume=ctx['dayBaseVlm'],
        quote_volume=ctx['dayNtlVlm'],
      )
      for ctx in ctxs
      if markets is None or ctx['coin'] in markets
    }

  @overload
  def trades_history(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeTrade]: ...

  @overload
  def trades_history(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[Trade]: ...

  @SDK.method
  @PaginatedResponse.lift
  async def trades_history(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fills of one pair, or of every pair with market IDs."""
    if market_id is not None:
      async for page in (await self.market(market_id)).trades_history(start, end):
        yield page
      return
    pages = self.client.info.user_fills_by_time_paged(
      self.shared.address, start_time=start, end_time=end
    )
    async for page in pages.via(self.shared.call):
      if rows := [exchange_trade(f) for f in page if is_spot_fill(f)]:
        yield rows


@dataclass(frozen=True, kw_only=True)
class PerpExchange(Public, SDKPerpExchange):
  """margin.trade USDC-margined perpetuals: one cross-margin wallet."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange ID."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """List the listed (not delisted) perpetuals."""
    universe = await self.shared.perp_universe()
    return [name for name, item in universe.items() if not item.get('isDelisted')]

  async def market(self, market_id: str, /) -> PerpMarket:
    """Resolve a perpetual by coin name."""
    universe = await self.shared.perp_universe()
    if market_id not in universe:
      raise ValueError(f'Unknown margin.trade perpetual: {market_id}')
    return PerpMarket(shared=self.shared, meta=universe[market_id])

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """24h volumes from the asset contexts; last and best bid/ask from CoinGecko,
    which omits some markets (`SPY`, `QQQ`): theirs stay `None`."""
    gecko = await self.shared.call(self.client.coingecko.derivatives.contracts)
    quotes = {row['base_currency']: row for row in gecko}
    return {
      name: quote_ticker(
        quotes.get(name),
        base_volume=ctx['dayBaseVlm'],
        quote_volume=ctx['dayNtlVlm'],
      )
      for name, (_, ctx) in (await self.shared.contexts()).items()
      if markets is None or name in markets
    }

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Oracle index, mark, funding and open interest from one `metaAndAssetCtxs`."""
    next_time = next_settlement(datetime.now(timezone.utc))
    return {
      name: PerpStats(
        index=ctx['oraclePx'],
        mark=ctx['markPx'],
        funding=ctx['funding'],
        next_funding_time=next_time,
        funding_interval=FUNDING_INTERVAL,
        open_interest=ctx['openInterest'],
      )
      for name, (_, ctx) in (await self.shared.contexts()).items()
      if markets is None or name in markets
    }

  @overload
  def trades_history(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeTrade]: ...

  @overload
  def trades_history(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[Trade]: ...

  @SDK.method
  @PaginatedResponse.lift
  async def trades_history(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fills of one perpetual, or of every perpetual with market IDs."""
    if market_id is not None:
      async for page in (await self.market(market_id)).trades_history(start, end):
        yield page
      return
    pages = self.client.info.user_fills_by_time_paged(
      self.shared.address, start_time=start, end_time=end
    )
    async for page in pages.via(self.shared.call):
      if rows := [exchange_trade(f) for f in page if not is_spot_fill(f)]:
        yield rows

  @overload
  def funding_payments(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeFundingPayment]: ...

  @overload
  def funding_payments(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]: ...

  @SDK.method
  @PaginatedResponse.lift
  async def funding_payments(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[FundingPayment]]:
    """Settlements of one perpetual, or of all of them with market IDs."""
    if market_id is not None:
      async for page in (await self.market(market_id)).funding_payments(start, end):
        yield page
      return
    rows = await self.shared.call(
      lambda: self.client.info.user_funding(
        self.shared.address, start_time=start, end_time=end
      )
    )
    if rows:
      yield [
        ExchangeFundingPayment(
          market_id=r['delta']['coin'], amount=r['delta']['usdc'], time=r['time']
        )
        for r in rows
      ]

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """The cross bucket, or a market's own bucket."""
    if market_id is not None:
      return await (await self.market(market_id)).perp_collateral()
    state = await self.shared.call(
      lambda: self.client.info.clearinghouse_state(user=self.shared.address)
    )
    return cross_collateral(state)
