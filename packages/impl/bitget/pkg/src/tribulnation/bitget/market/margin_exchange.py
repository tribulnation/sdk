"""Bitget's cross spot-margin exchange on a Unified Trading Account: every margin pair."""

from datetime import timedelta
from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
import asyncio

from tribulnation.sdk.market import Exchange, PerpCollateral, Settings, Ticker

from .impl import VenueMixin, parse_spot_ticker, uta_perp_collateral
from .margin_market import MarginMarket


@dataclass(kw_only=True, frozen=True)
class MarginExchange(VenueMixin, Exchange):
  """Bitget UTA cross spot margin (category `MARGIN`)."""

  @property
  def exchange_id(self) -> str:
    return 'margin'

  async def markets(self) -> Sequence[str]:
    """List the pairs tradable on margin."""
    return list(await self.margin_instruments())

  async def market(self, market_id: str, /) -> MarginMarket:
    """Fetch a margin pair by symbol, e.g. `LITUSDT`."""
    instruments = await self.margin_instruments()
    if market_id not in instruments:
      raise ValueError(f'Unknown Bitget margin market: {market_id!r}')
    return MarginMarket(account=self.account, cache=self.cache, symbol=market_id)

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
    ttl: timedelta | None = None,
  ) -> Mapping[str, Ticker]:
    """Fetch best bid/ask and last price of every margin pair: its spot ticker.

    Args:
      markets: Symbols to keep. `None` keeps every margin pair.
      settings: Accepted for interface compatibility and ignored.
    """
    tickers, instruments = await asyncio.gather(
      self.call(lambda: self.client.classic.spot.tickers(validate=self.validate)),
      self.margin_instruments(),
    )
    wanted = (
      instruments.keys() if markets is None else instruments.keys() & set(markets)
    )
    return {t['symbol']: parse_spot_ticker(t) for t in tickers if t['symbol'] in wanted}

  async def collateral(
    self, market_id: str | None = None, /, *, ttl: timedelta | None = None
  ) -> PerpCollateral:
    """Fetch the unified pool every margin pair (and perpetual) draws on.

    Args:
      market_id: Accepted for symmetry; every pair reports the same pool.

    Raises:
      NotImplementedError: The account is in Classic mode.
    """
    if not await self.is_uta():
      raise NotImplementedError(
        'Bitget spot margin is implemented for Unified Trading Accounts only.'
      )
    return await uta_perp_collateral(self)
