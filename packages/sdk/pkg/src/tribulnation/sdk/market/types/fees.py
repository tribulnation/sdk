"""Combined trading fee rates by liquidity role and order side."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, kw_only=True)
class Fees:
  """Combined rates as fractions of notional, excluding optional payment discounts.

  Includes applicable side, tax, special and market adjustments. Negative rates
  are rebates. These are current rates, not a guarantee about a future fill or
  fee-asset rounding/conversion. Unknown schedules are not representable here.
  """

  maker_buy: Decimal
  maker_sell: Decimal
  taker_buy: Decimal
  taker_sell: Decimal

  def __post_init__(self):
    """Reject missing, non-decimal and non-finite rates while allowing rebates."""
    for rate in (self.maker_buy, self.maker_sell, self.taker_buy, self.taker_sell):
      if not isinstance(rate, Decimal) or not rate.is_finite():
        raise ValueError('Combined fee rates must be finite Decimals')

  @classmethod
  def symmetric(cls, *, maker: Decimal, taker: Decimal) -> 'Fees':
    """Construct a schedule established to have identical buy and sell rates."""
    return cls(maker_buy=maker, maker_sell=maker, taker_buy=taker, taker_sell=taker)
