from typing_extensions import Collection, Mapping
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import PerpStats

from tribulnation.dydx.core import wrap_exceptions
from .mixin import ExchangeMixin

FUNDING_INTERVAL = timedelta(hours=1)
"""dYdX settles funding every hour, on the hour."""

@wrap_exceptions
async def perp_stats(self: ExchangeMixin, markets: Collection[str] | None = None) -> Mapping[str, PerpStats]:
  """Fetch pricing and funding stats for every perp market in one call.

  The indexer's `/perpetualMarkets` payload already covers every market, so this
  is a single request yielding a consistent cross-section. dYdX reports no mark
  price, so `mark` is always `None`.

  Args:
    markets: Market tickers to keep. `None` keeps every market.

  Returns:
    A mapping of market ticker to its `PerpStats`.

  References:
    - [dYdX API docs](https://docs.dydx.xyz/types/perpetual_market)
  """
  perpetual_markets = await self.shared.load_markets(refetch=True)
  now = datetime.now().astimezone()
  next_time = now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL
  wanted = list(perpetual_markets) if markets is None else list(markets)

  stats: dict[str, PerpStats] = {}
  for ticker in wanted:
    if (market := perpetual_markets.get(ticker)) is None:
      raise ValueError(f'Market not found: {ticker}')
    if (price := market.get('oraclePrice')) is None:
      raise ApiError(f'Oracle price unavailable for {ticker}')
    open_interest = market.get('openInterest')
    stats[ticker] = PerpStats(
      index=Decimal(price),
      funding=Decimal(market['nextFundingRate']),
      next_funding_time=next_time,
      funding_interval=FUNDING_INTERVAL,
      open_interest=Decimal(open_interest) if open_interest is not None else None,
    )
  return stats
