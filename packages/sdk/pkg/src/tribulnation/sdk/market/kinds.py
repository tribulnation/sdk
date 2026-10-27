"""Narrow a market or exchange to what it trades (ADR 0051).

Methods cannot narrow `self`, so these are functions: `if is_spot(market):` lets the
type checker see a `SpotMarket` in the branch.
"""

from typing_extensions import TypeIs, overload

from .market import Market, SpotMarket, MarginMarket, PerpMarket
from .exchange import Exchange, SpotExchange, PerpExchange


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


def is_margin(x: Market, /) -> TypeIs[MarginMarket]:
  """Whether `x` trades on margin (perpetuals today): it has `collateral_id()`,
  `position()` and `leverage()`."""
  return isinstance(x, MarginMarket)
