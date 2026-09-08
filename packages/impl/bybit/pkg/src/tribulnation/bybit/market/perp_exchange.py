"""Bybit's linear perpetual exchange: every `category='linear'` contract."""

from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from tribulnation.sdk.market import (
  PerpCollateral,
  PerpExchange as _PerpExchange,
  PerpStats,
  Settings,
  Ticker,
)
from typed_bybit.market.tickers import ContractTicker

from tribulnation.bybit.core import num
from .impl import VenueMixin
from .perp_market import PerpMarket


@dataclass(kw_only=True, frozen=True)
class PerpExchange(VenueMixin, _PerpExchange):
  """Bybit linear perpetuals."""

  @property
  def venue_id(self) -> str:
    return 'bybit'

  @property
  def exchange_id(self) -> str:
    return 'perp'

  async def markets(self) -> Sequence[str]:
    """List available linear perpetual contracts."""
    return list(await self.perp_instruments())

  async def market(self, market_id: str, /) -> PerpMarket:
    """Fetch a linear perpetual contract by symbol, e.g. `BTCUSDT`."""
    instruments = await self.perp_instruments()
    if market_id not in instruments:
      raise ValueError(f'Unknown Bybit linear perpetual market: {market_id!r}')
    return PerpMarket(
      client=self.client,
      settings=self.settings,
      cache=self.cache,
      symbol=market_id,
    )

  async def linear_tickers(self) -> Sequence[ContractTicker]:
    """Fetch the raw ticker row of every contract in the `linear` category.

    The category also carries dated futures, which pay no funding and report
    `fundingRate=''` and `nextFundingTime='0'`; callers filter to perpetuals.
    """
    tickers = await self.call_bybit(
      lambda: self.client.market.tickers('linear', validate=self.validate)
    )
    assert tickers['category'] == 'linear'
    return tickers['list']

  async def tickers(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch best bid/ask and last price for every perpetual in one call.

    Args:
      markets: Symbols to keep. `None` keeps every perpetual.
      settings: Accepted for interface compatibility and ignored -- Bybit serves the
        whole book of tickers in one request either way.
    """
    rows = await self.linear_tickers()
    instruments = await self.perp_instruments()
    wanted = (
      instruments.keys() if markets is None else instruments.keys() & set(markets)
    )
    return {
      t['symbol']: Ticker(
        last=t['lastPrice'],
        bid=t['bid1Price'],
        ask=t['ask1Price'],
        bid_qty=t['bid1Size'],
        ask_qty=t['ask1Size'],
        base_volume_24h=t['volume24h'],
      )
      for t in rows
      if t['symbol'] in wanted
    }

  async def perp_stats(
    self,
    markets: Collection[str] | None = None,
    *,
    settings: Settings = {},
  ) -> Mapping[str, PerpStats]:
    """Fetch pricing and funding stats for every perpetual in one call.

    Args:
      markets: Symbols to keep. `None` keeps every perpetual.
      settings: Accepted for interface compatibility and ignored -- Bybit reports the
        index price directly, so there is no oracle-vs-mark choice to make.
    """
    rows = await self.linear_tickers()
    instruments = await self.perp_instruments()
    wanted = (
      instruments.keys() if markets is None else instruments.keys() & set(markets)
    )
    stats: dict[str, PerpStats] = {}
    for t in rows:
      symbol = t['symbol']
      if symbol not in wanted:
        continue
      next_funding_time = t['nextFundingTime']
      stats[symbol] = PerpStats(
        index=t['indexPrice'],
        mark=t['markPrice'],
        # Only a dated future reports `fundingRate=''`, and `markets()` lists none.
        funding=num(t['fundingRate']),
        next_funding_time=None if next_funding_time == '0' else next_funding_time,
        funding_interval=timedelta(minutes=instruments[symbol]['fundingInterval']),
        open_interest=t['openInterest'],
      )
    return stats

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """Fetch the Unified Trading Account's margin pool.

    Bybit runs one margin pool per unified account rather than one per contract, so
    a `market_id` selects nothing different -- it is accepted for interface
    compatibility and resolves to the same bucket.
    """
    account = await self.unified_balance()
    if account is None:
      return PerpCollateral(
        equity=Decimal(0),
        free_collateral=Decimal(0),
        initial_margin=Decimal(0),
        maintenance_margin=Decimal(0),
        leverage=Decimal(0),
        margin_mode='cross',
      )
    info = await self.call_bybit(
      lambda: self.client.account.info(validate=self.validate)
    )
    positions = await self.linear_positions()
    notional = sum((num(p['positionValue']).copy_abs() for p in positions), Decimal(0))
    equity = num(account['totalEquity'])
    return PerpCollateral(
      equity=equity,
      free_collateral=num(account['totalAvailableBalance']),
      initial_margin=num(account['totalInitialMargin']),
      maintenance_margin=num(account['totalMaintenanceMargin']),
      leverage=notional / equity if equity > 0 else Decimal(0),
      margin_mode='isolated' if info['marginMode'] == 'ISOLATED_MARGIN' else 'cross',
    )
