from decimal import Decimal

from tribulnation.sdk.core import ApiError
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

def effective_mmf(market: PerpetualMarket):
  """Compute the effective Maintenance Margin Fraction (MMF) of the given market.

  dYdX scales the Initial Margin Fraction up with open interest (see `effective_imf`).
  We assume the *same* OI scaling factor applies to the Maintenance Margin Fraction, so
  maintenance margin isn't understated at high open interest:

    effective_mmf = effective_imf(market) * base_mmf / base_imf

  where `base_imf = market['initialMarginFraction']` and
  `base_mmf = market['maintenanceMarginFraction']`.

  NOTE: the "OI-scaling-applies-to-MMF" assumption should be confirmed against the dYdX
  margin docs (https://docs.dydx.xyz/concepts/trading/margin#margining). Scaling *up* is
  the risk-safe direction (maintenance is over- rather than under-stated).
  """
  base_imf = market['initialMarginFraction']
  base_mmf = market['maintenanceMarginFraction']
  if base_imf == 0:
    return base_mmf
  return effective_imf(market) * base_mmf / base_imf

def max_leverage(market: PerpetualMarket):
  """Return the maximum leverage implied by market margin metadata."""
  imf = effective_imf(market)
  return Decimal(1) / imf
