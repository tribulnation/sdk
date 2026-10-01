"""Hyperliquid trading limits and price rounding."""

from decimal import Decimal, ROUND_HALF_UP

PRICE_MAX_DECIMALS = 5
"""See https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size"""
SPOT_PRICE_MAX_DECIMALS = 8
"""See https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size"""
FUTURES_PRICE_MAX_DECIMALS = 6
"""See https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size"""
MAX_SIGNIFICANT_FIGURES = 5
"""See https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size"""
MIN_ORDER_VALUE = Decimal(10)  # MIN ORDER VALUE IN USD
"""Not specified in the docs, but the API returns errors for orders with less than $10."""
MIN_RELATIVE_PRICE = Decimal('0.2')
"""Not specified in the docs, but the API returns errors for orders >80% away from the current price."""
MAX_RELATIVE_PRICE = Decimal('1.8')
"""Not specified in the docs, but the API returns errors for orders >80% away from the current price."""


def plain_decimal(x: Decimal) -> Decimal:
  """
  Write `x` in positional form without fractional trailing zeros, as the venue parses and signs it.

  `Decimal.normalize()`, which the SDK's tick and step rounding applies, turns round
  numbers into exponent form (`40` into `4E+1`). The typed client serializes that as is,
  and the API rejects it with a 422 ("Failed to deserialize the JSON body").
  """
  return Decimal(f'{x.normalize():f}')


def round_price(price: Decimal, max_sig_figs: int = MAX_SIGNIFICANT_FIGURES) -> Decimal:
  """
  Round `price` to at most `max_sig_figs` significant figures without trailing zeros.

  Integer prices are exempt from the significant-figure limit. Remove fractional
  trailing zeros before signing, while keeping integers in ordinary decimal form.

  References:
    - https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size
  """
  if price.is_zero():
    return Decimal(0)

  if price >= 10000:
    return plain_decimal(price.to_integral_value())

  x = price.normalize()
  k = x.adjusted()

  # Number of decimal places needed to keep `max_sig_figs` significant digits
  decimal_places = max_sig_figs - 1 - k

  # quant = 10^(-decimal_places); works for positive or negative decimal_places
  quant = Decimal(1).scaleb(-decimal_places)

  rounded = x.quantize(quant, rounding=ROUND_HALF_UP)
  if rounded == rounded.to_integral_value():
    return rounded.to_integral_value()
  return rounded.normalize()
