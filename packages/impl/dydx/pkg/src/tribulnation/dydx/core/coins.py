from decimal import Decimal
from typed_dydx.protos.cosmos.base.v1beta1 import Coin, DecCoin
from .constants import (
  DYDX_MAINNET_USDC_DENOM,
  DYDX_MAINNET_DYDX_DENOM,
  DYDX_TESTNET_USDC_DENOM,
  DYDX_TESTNET_DYDX_DENOM,
  USDC_QUANTUMS,
  DYDX_QUANTUMS,
  USDC,
  DYDX,
)


def parse_denom_amount(denom: str, amount: Decimal | int | str):
  """
  Resolve a chain denom to its SDK asset and scale its integer amount.

  Args:
    denom: The bank denom, mainnet or testnet.
    amount: The amount in the denom's smallest unit.

  Raises:
    ValueError: The denom is not USDC or the native token on either network.
  """
  if denom in (DYDX_MAINNET_USDC_DENOM, DYDX_TESTNET_USDC_DENOM):
    return USDC, Decimal(amount) / USDC_QUANTUMS
  elif denom in (DYDX_MAINNET_DYDX_DENOM, DYDX_TESTNET_DYDX_DENOM):
    return DYDX, Decimal(amount) / DYDX_QUANTUMS
  else:
    raise ValueError(f'Unknown denom: {denom}')


def parse_coin(coin: Coin) -> tuple[str, Decimal]:
  return parse_denom_amount(coin.denom, coin.amount)


def parse_dec_coin(coin: DecCoin):
  amount = Decimal(coin.amount) / DYDX_QUANTUMS  # legacy 10^18 repr
  return parse_denom_amount(coin.denom, amount)


def parse_dydx_quantums(quantums: int | str):
  return Decimal(int(quantums)) / DYDX_QUANTUMS


def parse_usdc_quantums(quantums: int | str):
  return Decimal(int(quantums)) / USDC_QUANTUMS
