"""Bitget's perpetual exchange: every USDT-margined perpetual contract."""

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
import asyncio

from tribulnation.sdk.market import (
  PerpCollateral,
  PerpExchange as _PerpExchange,
  PerpStats,
  Settings,
  Ticker,
)

from .impl import (
  PERP,
  VenueMixin,
  parse_perp_stats,
  parse_perp_ticker,
  uta_perp_collateral,
)
from .impl.account import not_supported_classic_collateral
from .perp_market import PerpMarket


@dataclass(kw_only=True, frozen=True)
class PerpExchange(VenueMixin, _PerpExchange):
  """Bitget USDT-margined perpetuals."""

  @property
  def venue_id(self) -> str:
    return 'bitget'

  @property
  def exchange_id(self) -> str:
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """List available perpetual contracts."""
    return list(await self.perp_contracts())

  async def market(self, market_id: str, /) -> PerpMarket:
    """Fetch a perpetual contract by symbol, e.g. `BTCUSDT`."""
    contracts = await self.perp_contracts()
    if market_id not in contracts:
      raise ValueError(f'Unknown Bitget perpetual market: {market_id!r}')
    return PerpMarket(account=self.account, cache=self.cache, symbol=market_id)

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch best bid/ask and last price for every perpetual in one call.

    Args:
      markets: Symbols to keep. `None` keeps every perpetual.
      settings: Accepted for interface compatibility and ignored -- Bitget serves the
        whole book of tickers in one request either way.
    """
    rows, contracts = await asyncio.gather(
      self.call(
        lambda: self.client.classic.mix.market.tickers(PERP, validate=self.validate)
      ),
      self.perp_contracts(),
    )
    wanted = contracts.keys() if markets is None else contracts.keys() & set(markets)
    return {t['symbol']: parse_perp_ticker(t) for t in rows if t['symbol'] in wanted}

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, PerpStats]:
    """Fetch pricing and funding stats for every perpetual in two calls.

    The ticker listing carries index, mark, the current rate and open interest; the
    settlement time and interval come from the UTA v3 public funding-rate listing,
    which serves every account mode (its Classic v2 twin fails validation on the
    whole universe, see `PerpMarket.next_funding`).

    Args:
      markets: Symbols to keep. `None` keeps every perpetual.
      settings: Accepted for interface compatibility and ignored -- Bitget reports the
        index price directly, so there is no oracle-vs-mark choice to make.
    """
    rows, rates, contracts = await asyncio.gather(
      self.call(
        lambda: self.client.classic.mix.market.tickers(PERP, validate=self.validate)
      ),
      self.call(
        lambda: self.client.uta.market.funding_rate.current(
          PERP, validate=self.validate
        )
      ),
      self.perp_contracts(),
    )
    funding = {r['symbol']: r for r in rates}
    wanted = contracts.keys() if markets is None else contracts.keys() & set(markets)
    return {
      t['symbol']: parse_perp_stats(t, funding.get(t['symbol']))
      for t in rows
      if t['symbol'] in wanted
    }

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """Fetch perpetual collateral.

    A UTA account has one margin pool across every product line: `market_id` selects
    the margin mode configured for that contract, `None` reports the pool as `cross`.
    A Classic account reports no margin requirement figures at all, so it raises
    `NotImplementedError`.
    """
    if market_id is not None:
      market = await self.market(market_id)
      return await market.perp_collateral()
    if await self.is_uta():
      return await uta_perp_collateral(self)
    raise not_supported_classic_collateral()
