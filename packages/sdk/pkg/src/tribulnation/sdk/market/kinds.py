"""Narrow a market or exchange to what it trades (ADR 0051, ADR 0073).

Methods cannot narrow `self`, so these are functions: `if is_spot(market):` lets the
type checker see a `SpotMarket` in the branch.
"""

from typing_extensions import TypeIs, overload

from .market import Market, SpotMarket, MarginMarket, PerpMarket
from .exchange import Exchange, SpotExchange, MarginExchange, PerpExchange


@overload
def is_spot(x: Market, /) -> TypeIs[SpotMarket]: ...
@overload
def is_spot(x: Exchange, /) -> TypeIs[SpotExchange]: ...
def is_spot(x: Market | Exchange, /) -> bool:
  """Whether `x` is a spot market or exchange."""
  return isinstance(x, (SpotMarket, SpotExchange))


@overload
def is_perp(x: Market, /) -> TypeIs[PerpMarket]: ...
@overload
def is_perp(x: Exchange, /) -> TypeIs[PerpExchange]: ...
def is_perp(x: Market | Exchange, /) -> bool:
  """Whether `x` is a perpetual market or exchange."""
  return isinstance(x, (PerpMarket, PerpExchange))


@overload
def is_margin(x: Market, /) -> TypeIs[MarginMarket]: ...
@overload
def is_margin(x: Exchange, /) -> TypeIs[MarginExchange]: ...
def is_margin(x: Market | Exchange, /) -> bool:
  """Whether `x` trades on margin: it has `collateral_id()`, `position()`,
  `leverage()` and `interest_payments()`.

  True for kind `'margin'` (spot pairs on borrowed money) and for perpetuals, which
  are margin markets too; `x.kind == 'margin'` tells the first apart.
  """
  return isinstance(x, (MarginMarket, MarginExchange))
