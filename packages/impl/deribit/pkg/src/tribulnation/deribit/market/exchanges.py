"""Public native discovery, product-scoped summaries and linear perpetual statistics."""

from datetime import timedelta
from dataclasses import dataclass
from decimal import Decimal
from typing_extensions import Collection, Literal, Mapping, Sequence
from tribulnation.sdk.market import Exchange, PerpExchange, PerpStats, Settings, Ticker
from .common import Public, product, Product
from .markets import SpotMarket, NativeSpotMarket, LinearPerpMarket


@dataclass(frozen=True, kw_only=True)
class SpotExchange(Public, Exchange):
  """Spot instruments, including explicitly candle-less Coinbase-routed pairs."""

  @property
  def exchange_id(self) -> Product:
    """The explicit Catalogue spot identity."""
    return 'spot'

  async def markets(self) -> Sequence[str]:
    """List only active instruments of this supported product."""
    return [
      name
      for name, row in (await self.shared.symbols()).items()
      if product(row) == self.exchange_id
    ]

  async def market(self, market_id: str, /) -> SpotMarket:
    """Use current cached routing metadata to select candle availability."""
    row = (await self.shared.symbols()).get(market_id)
    if row is None or product(row) != self.exchange_id:
      raise ValueError(f'Unknown or unsupported Deribit spot market: {market_id}')
    cls = (
      SpotMarket if row.get('is_csr') or row.get('is_cbe_routed') else NativeSpotMarket
    )
    return cls(shared=self.shared, symbol=market_id)

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, Ticker]:
    """Read product-specific summaries; never pull unrelated option records."""
    if markets is not None and not markets:
      return {}
    definitions = await self.shared.symbols()
    selected = {
      name: row
      for name, row in definitions.items()
      if product(row) == self.exchange_id and (markets is None or name in markets)
    }
    currencies = {
      r['base_currency'] if self.exchange_id == 'spot' else r['quote_currency']
      for r in selected.values()
    }
    kind: Literal['spot', 'future'] = 'spot' if self.exchange_id == 'spot' else 'future'
    summaries = await self.shared.summaries(currencies, kind=kind)
    return {
      name: Ticker(
        last=None if row['last'] is None else Decimal(str(row['last'])),
        bid=None if row['bid_price'] is None else Decimal(str(row['bid_price'])),
        ask=None if row['ask_price'] is None else Decimal(str(row['ask_price'])),
        base_volume_24h=Decimal(str(row['volume'])),
        quote_volume_24h=Decimal(str(row['volume_notional']))
        if 'volume_notional' in row
        else None,
      )
      for name, row in summaries.items()
      if name in selected
    }


@dataclass(frozen=True, kw_only=True)
class LinearPerpExchange(SpotExchange, PerpExchange):
  """Active linear perpetuals whose quote and settlement assets agree."""

  @property
  def exchange_id(self) -> Product:
    """The explicit perpetual identity, excluding inverse and dated contracts."""
    return 'perp'

  async def market(self, market_id: str, /) -> LinearPerpMarket:
    """Reject every ID outside the supported discovery inventory."""
    row = (await self.shared.symbols()).get(market_id)
    if row is None or product(row) != 'perp':
      raise ValueError(f'Unknown or unsupported Deribit linear perpetual: {market_id}')
    return LinearPerpMarket(shared=self.shared, symbol=market_id)

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, PerpStats]:
    """Read native index, mark and base open interest, one request per quote currency.

    A perpetual's estimated delivery price is its index price, so the futures book
    summaries carry every field of the ticker path. An instrument missing from the
    summaries, or without an estimated delivery price, falls back to its paced ticker.
    """
    if markets is not None and not markets:
      return {}
    definitions = await self.shared.symbols()
    selected = [s for s in await self.markets() if markets is None or s in markets]
    summaries = (
      await self.shared.summaries(
        {definitions[s]['quote_currency'] for s in selected}, kind='future'
      )
      if selected
      else {}
    )
    result: dict[str, PerpStats] = {}
    for symbol in selected:
      row = summaries.get(symbol)
      if row is not None and 'estimated_delivery_price' in row:
        native, index = row, row['estimated_delivery_price']
      else:
        native = await self.shared.ticker(symbol)
        index = native['index_price']
      result[symbol] = PerpStats(
        index=Decimal(str(index)),
        mark=Decimal(str(native['mark_price'])),
        open_interest=None
        if 'open_interest' not in native
        else Decimal(str(native['open_interest'])),
      )
    return result
