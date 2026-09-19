"""Public native discovery, product-scoped summaries and linear perpetual statistics."""

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
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
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
    result: dict[str, Ticker] = {}
    for currency in sorted(currencies):
      rows = await self.shared.call(
        lambda: self.shared.client.market_data.get_book_summary_by_currency(
          currency=currency, kind=kind
        )
      )
      for row in rows:
        name = row['instrument_name']
        if name in selected:
          result[name] = Ticker(
            last=None if row['last'] is None else Decimal(str(row['last'])),
            bid=None if row['bid_price'] is None else Decimal(str(row['bid_price'])),
            ask=None if row['ask_price'] is None else Decimal(str(row['ask_price'])),
            base_volume_24h=Decimal(str(row['volume'])),
          )
    return result


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
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Read native index, mark and base open interest with shared request pacing."""
    if markets is not None and not markets:
      return {}
    selected = [s for s in await self.markets() if markets is None or s in markets]
    result: dict[str, PerpStats] = {}
    for symbol in selected:
      row = await self.shared.ticker(symbol)
      result[symbol] = PerpStats(
        index=Decimal(str(row['index_price'])),
        mark=Decimal(str(row['mark_price'])),
        open_interest=None
        if 'open_interest' not in row
        else Decimal(str(row['open_interest'])),
      )
    return result
