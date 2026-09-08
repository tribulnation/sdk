"""Bitget's spot exchange: every spot pair."""

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass

from tribulnation.sdk.market import Collateral, Exchange, Settings, Ticker

from .impl import VenueMixin, parse_spot_ticker, uta_pool
from .spot_market import SpotMarket


@dataclass(kw_only=True, frozen=True)
class SpotExchange(VenueMixin, Exchange):
  """Bitget spot."""

  @property
  def venue_id(self) -> str:
    return 'bitget'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def markets(self) -> Sequence[str]:
    """List available spot pairs."""
    return list(await self.spot_symbols())

  async def market(self, market_id: str, /) -> SpotMarket:
    """Fetch a spot pair by symbol, e.g. `BTCUSDT`."""
    symbols = await self.spot_symbols()
    if market_id not in symbols:
      raise ValueError(f'Unknown Bitget spot market: {market_id!r}')
    return SpotMarket(account=self.account, cache=self.cache, symbol=market_id)

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch best bid/ask and last price for every spot pair in one call.

    Args:
      markets: Symbols to keep. `None` keeps every symbol.
      settings: Accepted for interface compatibility and ignored -- Bitget serves the
        whole book of tickers in one request either way.
    """
    tickers = await self.call(
      lambda: self.client.classic.spot.tickers(validate=self.validate)
    )
    wanted = None if markets is None else set(markets)
    return {
      t['symbol']: parse_spot_ticker(t)
      for t in tickers
      if wanted is None or t['symbol'] in wanted
    }

  async def collateral(self, market_id: str | None = None, /) -> Collateral:
    """Fetch collateral.

    Args:
      market_id: A spot pair, whose quote-asset balance is returned. `None` returns
        the whole pool, which only a UTA account has: Classic keeps spot balances per
        coin with no pool-level figure, so it raises `NotImplementedError`.
    """
    if market_id is not None:
      market = await self.market(market_id)
      return await market.collateral()
    if await self.is_uta():
      return await uta_pool(self)
    raise NotImplementedError(
      'not supported on a Classic account: the spot wallet is a list of per-coin '
      'balances with no pool-level equity figure'
    )
