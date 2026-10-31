"""Hyperliquid trading limits and price rounding."""

from decimal import Decimal

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


def tick_size(sz_decimals: int, *, max_decimals: int) -> Decimal:
  """The finest price step: `max_decimals - szDecimals` decimal places.

  Coarser prices also need at most `MAX_SIGNIFICANT_FIGURES` significant figures,
  integers excepted (`Rules.sig_figs`).

  References:
    - https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size
  """
  return Decimal(10) ** -(max_decimals - sz_decimals)
