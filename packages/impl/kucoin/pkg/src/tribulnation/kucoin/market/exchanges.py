"""Native discovery, ticker selection and public perpetual statistics."""

from dataclasses import dataclass
from decimal import Decimal
from typing_extensions import Collection, Mapping, Sequence

from tribulnation.sdk.market import Exchange, PerpExchange, PerpStats, Settings, Ticker
from .common import Public
from .markets import LinearPerpMarket, SpotMarket


def positive_price(value: Decimal | None) -> Decimal | None:
  """Preserve absent prices and normalize nonpositive quotes to an empty side."""
  return value if value is not None and value > 0 else None


@dataclass(frozen=True, kw_only=True)
class SpotExchange(Public, Exchange):
  """Classic spot public market data."""

  @property
  def exchange_id(self) -> str:
    """The Catalogue spot exchange ID."""
    return 'spot'

  async def markets(self) -> Sequence[str]:
    """Discover enabled native symbols."""
    return [
      s for s, row in (await self.shared.spot_symbols()).items() if row['enableTrading']
    ]

  async def market(self, market_id: str, /) -> SpotMarket:
    """Reject unknown IDs before constructing a market object."""
    if market_id not in await self.shared.spot_symbols():
      raise ValueError(f'Unknown KuCoin spot market: {market_id}')
    return SpotMarket(shared=self.shared, symbol=market_id)

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Return native bid/ask prices and sizes for the requested active universe."""
    if markets is not None and not markets:
      return {}
    selected = set(await self.markets())
    if markets is not None:
      selected.intersection_update(markets)
    rows = await self.shared.call(self.shared.client.spot.all_tickers)
    return {
      r['symbol']: Ticker(
        last=positive_price(r['last']),
        bid=positive_price(r['buy']),
        ask=positive_price(r['sell']),
        bid_qty=r['bestBidSize'] if positive_price(r['buy']) is not None else None,
        ask_qty=r['bestAskSize'] if positive_price(r['sell']) is not None else None,
        base_volume_24h=r['vol'],
        quote_volume_24h=r['volValue'],
      )
      for r in rows['ticker']
      if r['symbol'] in selected
    }


@dataclass(frozen=True, kw_only=True)
class LinearPerpExchange(Public, PerpExchange):
  """Active linear perpetuals on KuCoin's Classic Futures API."""

  @property
  def exchange_id(self) -> str:
    """The explicit perpetual product identity for the Catalogue handoff."""
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """Exclude dated and inverse contracts from discovery."""
    return list(await self.shared.perp_symbols())

  async def market(self, market_id: str, /) -> LinearPerpMarket:
    """Construct only a qualified linear perpetual, retaining its native ID."""
    row = (await self.shared.perp_symbols()).get(market_id)
    if row is None:
      raise ValueError(f'Unknown or unsupported KuCoin linear perpetual: {market_id}')
    return LinearPerpMarket(
      shared=self.shared,
      symbol=market_id,
      contract_multiplier=Decimal(str(row['multiplier'])),
    )

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Normalize top-of-book lots; the contract's 24h volume is already base units."""
    if markets is not None and not markets:
      return {}
    contracts = await self.shared.perp_symbols(refetch=True)
    rows = await self.shared.call(self.shared.client.futures.all_tickers)
    result: dict[str, Ticker] = {}
    for r in rows:
      c = contracts.get(r['symbol'])
      if c is None or (markets is not None and r['symbol'] not in markets):
        continue
      multiplier = Decimal(str(c['multiplier']))
      result[r['symbol']] = Ticker(
        last=r['price'] if r['price'] > 0 else None,
        bid=r['bestBidPrice'] if r['bestBidPrice'] > 0 else None,
        ask=r['bestAskPrice'] if r['bestAskPrice'] > 0 else None,
        bid_qty=Decimal(r['bestBidSize']) * multiplier
        if r['bestBidPrice'] > 0
        else None,
        ask_qty=Decimal(r['bestAskSize']) * multiplier
        if r['bestAskPrice'] > 0
        else None,
        base_volume_24h=Decimal(str(c['volumeOf24h'])),
        quote_volume_24h=Decimal(str(c['turnoverOf24h'])),
      )
    return result

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, PerpStats]:
    """Return published index, mark and base-unit open interest; use next_funding for funding."""
    if markets is not None and not markets:
      return {}
    rows = await self.shared.perp_symbols(refetch=True)
    return {
      symbol: PerpStats(
        index=Decimal(str(c['indexPrice'])),
        mark=Decimal(str(c['markPrice'])),
        open_interest=Decimal(c['openInterest']) * Decimal(str(c['multiplier'])),
      )
      for symbol, c in rows.items()
      if markets is None or symbol in markets
    }
