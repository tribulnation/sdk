"""Bybit's spot exchange: every `category='spot'` pair."""

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market import Collateral, Exchange, Settings, Ticker

from tribulnation.bybit.core import num
from .impl import VenueMixin
from .spot_market import SpotMarket


@dataclass(kw_only=True, frozen=True)
class SpotExchange(VenueMixin, Exchange):
  """Bybit spot."""

  @property
  def venue_id(self) -> str:
    return 'bybit'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def markets(self) -> Sequence[str]:
    """List available spot pairs."""
    return list(await self.spot_instruments())

  async def market(self, market_id: str, /) -> SpotMarket:
    """Fetch a spot pair by symbol, e.g. `BTCUSDT`."""
    instruments = await self.spot_instruments()
    if market_id not in instruments:
      raise ValueError(f'Unknown Bybit spot market: {market_id!r}')
    return SpotMarket(
      client=self.client,
      settings=self.settings,
      cache=self.cache,
      symbol=market_id,
    )

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch best bid/ask and last price for every spot pair in one call.

    Args:
      markets: Symbols to keep. `None` keeps every symbol.
      settings: Accepted for interface compatibility and ignored -- Bybit serves the
        whole book of tickers in one request either way.
    """
    tickers = await self.call_bybit(
      lambda: self.client.market.tickers('spot', validate=self.validate)
    )
    # `tickers()` reveals a 3-way union whatever the `category` argument was; narrow
    # it on the discriminant the three shapes share.
    assert tickers['category'] == 'spot'
    wanted = None if markets is None else set(markets)
    return {
      t['symbol']: Ticker(
        last=num(t['lastPrice']),
        bid=num(t['bid1Price']),
        ask=num(t['ask1Price']),
        bid_qty=num(t['bid1Size']),
        ask_qty=num(t['ask1Size']),
        base_volume_24h=num(t['volume24h']),
      )
      for t in tickers['list']
      if wanted is None or t['symbol'] in wanted
    }

  async def collateral(self, market_id: str | None = None, /) -> Collateral:
    """Fetch collateral.

    Args:
      market_id: A spot pair, whose quote-asset balance is returned. `None` returns
        the Unified Trading Account's whole pool, valued in USD.
    """
    if market_id is not None:
      market = await self.market(market_id)
      return await market.collateral()
    account = await self.unified_balance()
    if account is None:
      return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
    return Collateral(
      equity=num(account['totalEquity']),
      free_collateral=num(account['totalAvailableBalance']),
    )
