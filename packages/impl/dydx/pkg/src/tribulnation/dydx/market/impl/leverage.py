from decimal import Decimal

from tribulnation.sdk.core import ApiError
from typed_dydx.indexer.schemas import PerpetualMarket


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

  if (
    open_notional_lower_cap is None
    or open_notional_upper_cap is None
    or open_notional_upper_cap == open_notional_lower_cap
  ):
    return base_IMF

  scaling_factor = (open_notional - open_notional_lower_cap) / (
    open_notional_upper_cap - open_notional_lower_cap
  )
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


PPM = 1_000_000
"""Parts per million, the chain's unit for a custom initial margin fraction."""


def inverse(imf: Decimal) -> Decimal:
  """`1 / imf`, a whole multiple without an exponent (`10`, not `1E+1`)."""
  leverage = Decimal(1) / imf
  if leverage == leverage.to_integral_value():
    return leverage.quantize(Decimal(1))
  else:
    return leverage


def max_leverage(market: PerpetualMarket):
  """Return the maximum leverage implied by market margin metadata.

  A whole multiple is returned without an exponent (`10`, not `1E+1`).
  """
  return inverse(effective_imf(market))


def account_leverage(market: PerpetualMarket, custom_imf_ppm: int | None) -> Decimal:
  """The subaccount's leverage on a market: the inverse of the larger of the market's
  effective IMF and the subaccount's custom IMF, as the chain margins it
  (`LiquidityTier.GetInitialMarginQuoteQuantums`)."""
  imf = effective_imf(market)
  if custom_imf_ppm:
    imf = max(imf, Decimal(custom_imf_ppm) / PPM)
  return inverse(imf)


def custom_imf_ppm(leverage: Decimal, market: PerpetualMarket) -> int:
  """The custom IMF in ppm that sets `leverage` on `market` (`1_000_000 / leverage`).

  Raises:
    ValueError: `leverage` is not finite and positive, is below 1x, is above the
      market's maximum (its base IMF; the chain refuses a smaller custom IMF), or
      has no whole ppm IMF: `3` would be `333333.3…` and is refused, not rounded.
  """
  if not (leverage.is_finite() and leverage > 0):
    raise ValueError(f'Leverage must be a positive number, got {leverage}')
  ppm = Decimal(PPM) / leverage
  if ppm > PPM:
    raise ValueError(f'dYdX leverage must be at least 1, got {leverage}')
  if ppm != ppm.to_integral_value():
    raise ValueError(
      f'dYdX cannot set leverage {leverage}: 1000000 / leverage must be a whole number'
    )
  base_imf = market['initialMarginFraction']
  if ppm < base_imf * PPM:
    raise ValueError(
      f'dYdX leverage {leverage} is above the maximum of {market["ticker"]}: '
      f'{inverse(base_imf)}'
    )
  return int(ppm)
