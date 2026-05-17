"""Coin and denom helpers for dYdX reporting history."""

from decimal import Decimal

from dydx.node import DYDX_MAINNET_USDC_DENOM
from .constants import DYDX, DYDX_BASE_DENOM, DYDX_QUANTUMS, USDC, USDC_QUANTUMS

def asset_symbol(denom: str) -> str:
  """Return the reporting asset symbol for a dYdX chain denom."""
  if denom in {DYDX_MAINNET_USDC_DENOM, 'uusdc'}:
    return USDC
  if denom == DYDX_BASE_DENOM:
    return DYDX
  return denom

def denom_quantums(denom: str) -> Decimal:
  """Return the base-unit divisor for a dYdX chain denom."""
  if denom in {DYDX_MAINNET_USDC_DENOM, 'uusdc'}:
    return USDC_QUANTUMS
  if denom == DYDX_BASE_DENOM:
    return DYDX_QUANTUMS
  return Decimal(1)

def parse_coin(value: str) -> tuple[str, Decimal] | None:
  """Parse a single Cosmos coin amount into asset and decimal quantity."""
  for index, char in enumerate(value):
    if not char.isdigit():
      amount = Decimal(value[:index])
      denom = value[index:]
      return asset_symbol(denom), amount / denom_quantums(denom)
  return None

def parse_coins(value: str) -> list[tuple[str, Decimal]]:
  """Parse a comma-separated Cosmos coin amount string."""
  coins: list[tuple[str, Decimal]] = []
  for item in value.split(','):
    coin = parse_coin(item)
    if coin is not None:
      coins.append(coin)
  return coins

def parse_fee_coin(value: str) -> tuple[str, Decimal]:
  """Parse a transaction fee coin, rejecting multi-denom fees."""
  coins = parse_coins(value)
  if len(coins) != 1:
    raise ValueError(f'Expected one dYdX fee coin, got {len(coins)} from {value!r}.')
  return coins[0]
