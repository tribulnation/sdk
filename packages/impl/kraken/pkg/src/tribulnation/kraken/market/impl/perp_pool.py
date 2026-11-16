"""The multi-collateral pool behind every `PF_` perpetual of one account."""

from datetime import timedelta
from decimal import Decimal
from typing_extensions import TYPE_CHECKING
import asyncio

from tribulnation.sdk.market import PerpCollateral

from .perp_account import flex_account, flex_collateral, total_notional
from .perp_data import is_market_ticker

if TYPE_CHECKING:
  from .mixin import Shared


async def pool_collateral(shared: 'Shared', *, ttl: timedelta | None) -> PerpCollateral:
  """The multi-collateral pool, its leverage at mark prices.

  Mark prices come from the public tickers, read only when a position is open.

  Args:
    shared: The account's shared state.
    ttl: How old shared answers may be; `None` asks afresh.
  """
  perp = shared.perp
  accounts, positions = await asyncio.gather(
    perp.accounts(ttl=ttl), perp.positions(ttl=ttl)
  )
  rows = positions['openPositions']
  marks: dict[str, Decimal] = {}
  if rows:
    response = await perp.read(
      'tickers', shared.client.futures.tickers, ttl=ttl or timedelta(0)
    )
    marks = {
      t['symbol'].upper(): Decimal(str(t['markPrice']))
      for t in response['tickers']
      if is_market_ticker(t)
    }
  return flex_collateral(flex_account(accounts), notional=total_notional(rows, marks))
