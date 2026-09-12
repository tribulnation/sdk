"""Kraken's Spot exchange: the whole pair catalogue."""

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market import Exchange, Settings, Ticker

from typed_kraken.spot.market_data.ticker import AssetTicker

from .impl import ExchangeMixin
from .spot_market import SpotMarket


def parse_ticker(entry: AssetTicker) -> Ticker:
  """Map one `Ticker` row onto a `Ticker`.

  Kraken's fields are its wire shortcuts: `a`/`b` are `[price, whole lot volume,
  lot volume]`, `c` is `[price, lot volume]` of the last trade, and `v` is
  `[today, last 24 hours]` volume in base units.
  """
  ask = entry.get('a')
  bid = entry.get('b')
  last = entry.get('c')
  volume = entry.get('v')
  return Ticker(
    last=Decimal(last[0]) if last is not None else None,
    bid=Decimal(bid[0]) if bid is not None else None,
    ask=Decimal(ask[0]) if ask is not None else None,
    bid_qty=Decimal(bid[2]) if bid is not None else None,
    ask_qty=Decimal(ask[2]) if ask is not None else None,
    base_volume_24h=Decimal(volume[1]) if volume is not None else None,
  )


@dataclass(frozen=True, kw_only=True)
class SpotExchange(ExchangeMixin, Exchange):
  """Kraken implementation of `Exchange`."""

  @property
  def venue_id(self) -> str:
    return 'kraken'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def markets(self) -> Sequence[str]:
    pairs = await self.shared.load_pairs()
    return list(pairs)

  async def market(self, market_id: str, /) -> SpotMarket:
    pairs = await self.shared.load_pairs()
    return SpotMarket(shared=self.shared, meta={'pair': pairs[market_id]})

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch last price, best bid and best ask for every market in one call.

    `Ticker` answers for the whole catalogue in one request, keyed by internal
    pair name, so the answer is re-keyed by altname and filtered here.

    Args:
      markets: Altnames to keep. `None` keeps every listed pair.
      settings: Accepted for interface compatibility and ignored.
    """
    pairs = await self.shared.load_pairs()
    entries = await self.call_kraken(self.client.spot.market_data.ticker)
    wanted = list(pairs) if markets is None else [m for m in markets if m in pairs]
    return {
      altname: parse_ticker(entry)
      for altname in wanted
      if (entry := entries.get(pairs[altname]['key'])) is not None
    }
