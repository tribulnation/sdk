from decimal import Decimal

from trading_sdk.core import ApiError
from dydx.indexer.types import PerpetualMarket

def effective_imf(market: PerpetualMarket):
  """Compute the effective Initial Margin Fraction (IMF) of the given market.
  
  See the [docs](https://docs.dydx.xyz/concepts/trading/margin#margining) for details
  """
  price = market.get('oraclePrice')
  if price is None:
    raise ApiError('Oracle price unavailable')
  open_notional = market['openInterest'] * Decimal(price)
  open_notional_lower_cap = market.get('openInterestLowerCap')
  open_notional_upper_cap = market.get('openInterestUpperCap')
  base_IMF = market['initialMarginFraction']

  if open_notional_lower_cap is None or open_notional_upper_cap is None or open_notional_upper_cap == open_notional_lower_cap:
    return base_IMF
  
  scaling_factor = (open_notional - open_notional_lower_cap) / (open_notional_upper_cap - open_notional_lower_cap)
  IMF_increase = scaling_factor * (1 - base_IMF)
  effective_IMF = min(base_IMF + max(IMF_increase, 0), 1)
  return Decimal(effective_IMF)

def max_leverage(market: PerpetualMarket):
  imf = effective_imf(market)
  return Decimal(1) / imf