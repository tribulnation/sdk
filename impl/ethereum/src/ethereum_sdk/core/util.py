from decimal import Decimal

def wei2eth(wei: Decimal) -> Decimal:
  return wei / Decimal(10**18)

def gwei2eth(gwei: Decimal) -> Decimal:
  return gwei / Decimal(10**9)