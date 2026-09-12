"""Bit2Me's Trading Spot exchange: the whole market catalogue."""

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market import Exchange, Settings, Ticker

from typed_bit2me.v2.trading.tickers import Entry as TickerInfo

from .impl import ExchangeMixin
from .spot_market import SpotMarket


def parse_ticker(entry: TickerInfo) -> Ticker:
  """Map one `v2/trading/tickers` row onto a `Ticker`.

  Bit2Me quotes best bid and ask prices but no size at either, so `bid_qty` and
  `ask_qty` stay `None`.
  """
  last = entry.get('close')
  bid = entry.get('bid')
  ask = entry.get('ask')
  volume = entry.get('baseVolume')
  return Ticker(
    last=Decimal(str(last)) if last is not None else None,
    bid=Decimal(str(bid)) if bid is not None else None,
    ask=Decimal(str(ask)) if ask is not None else None,
    base_volume_24h=Decimal(str(volume)) if volume is not None else None,
  )


@dataclass(frozen=True, kw_only=True)
class SpotExchange(ExchangeMixin, Exchange):
  """Bit2Me implementation of `Exchange`."""

  @property
  def venue_id(self) -> str:
    return 'bit2me'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def markets(self) -> Sequence[str]:
    markets = await self.shared.load_markets()
    return list(markets)

  async def market(self, market_id: str, /) -> SpotMarket:
    markets = await self.shared.load_markets()
    return SpotMarket(shared=self.shared, meta={'info': markets[market_id]})

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch bulk tickers, or use symbol-specific reads for an explicit selection.

    Args:
      markets: Symbols to keep. `None` keeps every symbol.
      settings: Accepted for interface compatibility and ignored.

    An explicit selection uses one native ticker request per distinct symbol.
    Both endpoints can return stale or zero bid/ask despite a live order book.
    Native values are preserved; use `depth()` when current book quotes are needed.
    """
    wanted = None if markets is None else set(markets)
    if wanted is None:
      entries = await self.call_bit2me(self.client.v2.trading.tickers)
    else:
      entries: list[TickerInfo] = []
      for symbol in sorted(wanted):
        entries.extend(
          await self.call_bit2me(
            lambda symbol=symbol: self.client.v2.trading.tickers(symbol=symbol)
          )
        )
    return {
      symbol: parse_ticker(entry)
      for entry in entries
      if (symbol := entry.get('symbol')) and (wanted is None or symbol in wanted)
    }
