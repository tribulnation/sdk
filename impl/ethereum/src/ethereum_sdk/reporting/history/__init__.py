from trading_sdk.reporting import History as _History
from .alchemy import AlchemyHistory
from .etherscan import EtherscanHistory

# Included in the Etherscan free plan

def ethereum(address: str, *, api_key: str | None = None) -> _History:
  return EtherscanHistory.ethereum(address, api_key=api_key)

def arbitrum(address: str, *, api_key: str | None = None) -> _History:
  return EtherscanHistory.arbitrum(address, api_key=api_key)

def polygon(address: str, *, api_key: str | None = None) -> _History:
  return EtherscanHistory.polygon(address, api_key=api_key)

# These are not supported by the Etherscan free plan -> Alchemy

def bnb(address: str, *, api_key: str | None = None) -> _History:
  obj = AlchemyHistory.bnb(
    address,
    api_key=api_key,
  )
  obj.include_internal_transfers = False
  return obj

def base(address: str, *, api_key: str | None = None) -> _History:
  obj = AlchemyHistory.base(
    address,
    api_key=api_key,
  )
  obj.include_internal_transfers = False
  return obj

def avalanche(address: str, *, api_key: str | None = None) -> _History:
  obj = AlchemyHistory.avalanche(
    address,
    api_key=api_key,
  )
  obj.include_internal_transfers = False
  return obj

def optimism(address: str, *, api_key: str | None = None) -> _History:
  obj = AlchemyHistory.optimism(
    address,
    api_key=api_key,
  )
  obj.include_internal_transfers = False
  return obj
