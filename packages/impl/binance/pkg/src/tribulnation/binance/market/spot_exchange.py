from typing_extensions import Collection, Mapping, Sequence, cast
from dataclasses import dataclass
from decimal import Decimal

from typed_binance.schemas import Ticker24hrFull

from tribulnation.sdk.market import Exchange, Market, Settings, Ticker

from .impl import SharedMixin
from .impl.mixin import wrap_exceptions
from .spot_market import SpotMarket


@dataclass(frozen=True, kw_only=True)
class SpotExchange(SharedMixin, Exchange):
  """Binance's spot exchange."""

  @property
  def venue_id(self) -> str:
    return 'binance'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def markets(self) -> Sequence[str]:
    symbols = await self.shared.load_spot_symbols()
    return list(symbols.keys())

  async def market(self, market_id: str, /) -> Market:
    symbols = await self.shared.load_spot_symbols()
    if market_id not in symbols:
      raise ValueError(f'Unknown Binance spot market: {market_id!r}')
    return SpotMarket(shared=self.shared, symbol=market_id)

  @wrap_exceptions
  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Read spot tickers using bulk public data and cached market discovery.

    The FULL bulk response carries both top-of-book quantities and 24-hour
    base volume. Zero-sized book sides are absent, not executable zero quotes.
    Retired symbols absent from discovery are omitted. No futures endpoints or
    credentials are used.
    """
    if markets is not None and not markets:
      return {}
    symbols = await self.shared.load_spot_symbols()
    response = await self.client.spot.http.market.ticker_24hr(type='FULL')
    if not isinstance(response, list):
      raise ValueError('Binance bulk ticker response must be a list')
    # No symbol and explicit FULL select this branch of the endpoint's union.
    rows = cast(list[Ticker24hrFull], response)
    selected = None if markets is None else set(markets)
    result: dict[str, Ticker] = {}
    for row in rows:
      symbol = row['symbol']
      if symbol not in symbols:
        continue
      if selected is not None and symbol not in selected:
        continue
      bid_qty, ask_qty = Decimal(row['bidQty']), Decimal(row['askQty'])
      last = Decimal(row['lastPrice'])
      result[symbol] = Ticker(
        last=last if last > 0 else None,
        bid=Decimal(row['bidPrice']) if bid_qty > 0 else None,
        ask=Decimal(row['askPrice']) if ask_qty > 0 else None,
        bid_qty=bid_qty if bid_qty > 0 else None,
        ask_qty=ask_qty if ask_qty > 0 else None,
        base_volume_24h=Decimal(row['volume']),
      )
    if selected is not None and selected - result.keys():
      raise ValueError(
        f'Binance spot tickers not found: {sorted(selected - result.keys())}'
      )
    return result
