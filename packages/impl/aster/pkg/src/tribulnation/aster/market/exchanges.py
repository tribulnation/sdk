"""Spot and perpetual exchanges: discovery and bulk tickers.

Per-market methods use the SDK's default delegation to `market(market_id)`.
"""

from dataclasses import dataclass
from typing_extensions import Collection, Mapping, Sequence, TypedDict
from decimal import Decimal
from tribulnation.sdk.market import (
  Collateral,
  Exchange,
  PerpExchange as SDKPerpExchange,
  PerpStats,
  Settings,
  Ticker,
)
from ..core import Public
from .markets import PerpMarket, SpotMarket


class Stats(TypedDict):
  """The native 24h ticker fields shared by spot and futures."""

  symbol: str
  lastPrice: Decimal
  volume: Decimal
  quoteVolume: Decimal


class Quote(TypedDict):
  """The native best bid/ask fields shared by spot and futures."""

  symbol: str
  bidPrice: Decimal
  bidQty: Decimal
  askPrice: Decimal
  askQty: Decimal


def positive(value: Decimal) -> Decimal | None:
  """Aster reports an empty book side, or a symbol never traded, as price zero."""
  return value if value > 0 else None


def join_tickers(
  stats: Sequence[Stats], quotes: Sequence[Quote], symbols: Collection[str]
) -> dict[str, Ticker]:
  """Join rolling 24h statistics with best bid/ask by symbol; empty sides are `None`."""
  books = {q['symbol']: q for q in quotes}
  result: dict[str, Ticker] = {}
  for row in stats:
    if row['symbol'] not in symbols:
      continue
    quote = books.get(row['symbol'])
    bid = positive(quote['bidPrice']) if quote else None
    ask = positive(quote['askPrice']) if quote else None
    result[row['symbol']] = Ticker(
      last=positive(row['lastPrice']),
      base_volume_24h=row['volume'],
      quote_volume_24h=row['quoteVolume'],
      bid=bid,
      ask=ask,
      bid_qty=quote['bidQty'] if quote and bid is not None else None,
      ask_qty=quote['askQty'] if quote and ask is not None else None,
    )
  return result


def selected(available: Collection[str], markets: Collection[str] | None) -> set[str]:
  """The requested subset of available symbols, or all of them."""
  return set(available) if markets is None else set(available) & set(markets)


@dataclass(frozen=True, kw_only=True)
class SpotExchange(Public, Exchange):
  """Aster spot."""

  @property
  def exchange_id(self) -> str:
    """The spot exchange ID."""
    return 'spot'

  async def markets(self) -> Sequence[str]:
    """List native symbols currently trading."""
    return list(await self.shared.spot_symbols())

  async def market(self, market_id: str, /) -> SpotMarket:
    """Resolve a trading symbol."""
    if market_id not in await self.shared.spot_symbols():
      raise ValueError(f'Unknown Aster spot market: {market_id}')
    return SpotMarket(shared=self.shared, symbol=market_id)

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Read 24h statistics and best bid/ask for all or the selected symbols."""
    if markets is not None and not markets:
      return {}
    symbols = selected(await self.shared.spot_symbols(refetch=True), markets)
    market = self.client.spot.market
    stats = await self.shared.call(market.ticker_24hr)
    quotes = await self.shared.call(market.book_ticker)
    return join_tickers(
      stats if isinstance(stats, list) else [stats],
      quotes if isinstance(quotes, list) else [quotes],
      symbols,
    )


@dataclass(frozen=True, kw_only=True)
class PerpExchange(Public, SDKPerpExchange):
  """Aster linear perpetuals, on a single cross-margin bucket."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange ID."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """List perpetual contracts currently trading."""
    return list(await self.shared.perp_symbols())

  async def market(self, market_id: str, /) -> PerpMarket:
    """Resolve a trading perpetual."""
    if market_id not in await self.shared.perp_symbols():
      raise ValueError(f'Unknown Aster perpetual: {market_id}')
    return PerpMarket(shared=self.shared, symbol=market_id)

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Read 24h statistics and best bid/ask for all or the selected contracts."""
    if markets is not None and not markets:
      return {}
    symbols = selected(await self.shared.perp_symbols(refetch=True), markets)
    market = self.client.futures.market
    stats = await self.shared.call(market.ticker_24hr)
    quotes = await self.shared.call(market.book_ticker)
    return join_tickers(
      stats if isinstance(stats, list) else [stats],
      quotes if isinstance(quotes, list) else [quotes],
      symbols,
    )

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Unsupported: typed-aster rejects the bulk funding configuration."""
    raise NotImplementedError('Aster bulk perpetual statistics are not supported')

  async def collateral(self, market_id: str | None = None, /) -> Collateral:
    """Read the cross-margin bucket, or a market's own collateral."""
    if market_id is not None:
      return await (await self.market(market_id)).collateral()
    return await self.shared.cross_collateral()
