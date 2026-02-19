from decimal import Decimal

PRICE_MAX_DECIMALS = 5
"""See https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size"""
SPOT_PRICE_MAX_DECIMALS = 8
"""See https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size"""
FUTURES_PRICE_MAX_DECIMALS = 6
"""See https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size"""
MIN_ORDER_VALUE = Decimal(10) # MIN ORDER VALUE IN USD
"""Not specified in the docs, but the API returns errors for orders with less than $10."""
MIN_RELATIVE_PRICE = Decimal('0.2')
"""Not specified in the docs, but the API returns errors for orders >80% away from the current price."""
MAX_RELATIVE_PRICE = Decimal('1.8')
"""Not specified in the docs, but the API returns errors for orders >80% away from the current price."""