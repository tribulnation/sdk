from trading_sdk.reporting import History as _History
from .alchemy import History as AlchemyHistory
from .etherscan import History as EtherscanHistory

# Included in the Etherscan free plan

def ethereum(address: str, *, api_key: str | None = None, ignore_zero_value: bool = True) -> _History:
  return EtherscanHistory.ethereum(address, api_key=api_key, ignore_zero_value=ignore_zero_value)

def arbitrum(address: str, *, api_key: str | None = None, ignore_zero_value: bool = True) -> _History:
  return EtherscanHistory.arbitrum(address, api_key=api_key, ignore_zero_value=ignore_zero_value)

def polygon(address: str, *, api_key: str | None = None, ignore_zero_value: bool = True) -> _History:
  return EtherscanHistory.polygon(address, api_key=api_key, ignore_zero_value=ignore_zero_value)

# These are not supported by the Etherscan free plan -> Alchemy

def bnb(address: str, *, api_key: str | None = None, ignore_zero_value: bool = True) -> _History:
  return AlchemyHistory.bnb(
    address,
    api_key=api_key,
    ignore_zero_value=ignore_zero_value,
    include_internal_transfers=False,
  )

def base(address: str, *, api_key: str | None = None, ignore_zero_value: bool = True) -> _History:
  return AlchemyHistory.base(
    address,
    api_key=api_key,
    ignore_zero_value=ignore_zero_value,
    include_internal_transfers=False,
  )

def avalanche(address: str, *, api_key: str | None = None, ignore_zero_value: bool = True) -> _History:
  return AlchemyHistory.avalanche(
    address,
    api_key=api_key,
    ignore_zero_value=ignore_zero_value,
    include_internal_transfers=False,
  )

def optimism(address: str, *, api_key: str | None = None, ignore_zero_value: bool = True) -> _History:
  return AlchemyHistory.optimism(
    address,
    api_key=api_key,
    ignore_zero_value=ignore_zero_value,
    include_internal_transfers=False,
  )
