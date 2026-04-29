from alchemy import BNB_ALCHEMY_URL, BASE_ALCHEMY_URL, AVAX_ALCHEMY_URL, OPTIMISM_ALCHEMY_URL
from .alchemy import AlchemyHistory
from .etherscan import EtherscanHistory

# Included in the Etherscan free plan

def ethereum(address: str, *, api_key: str | None = None, rate_limit: int | None = None):
  return EtherscanHistory.etherscan_ethereum(address, api_key=api_key, rate_limit=rate_limit)

def arbitrum(address: str, *, api_key: str | None = None, rate_limit: int | None = None):
  return EtherscanHistory.etherscan_arbitrum(address, api_key=api_key, rate_limit=rate_limit)

def polygon(address: str, *, api_key: str | None = None, rate_limit: int | None = None):
  return EtherscanHistory.etherscan_polygon(address, api_key=api_key, rate_limit=rate_limit)

# These are not supported by the Etherscan free plan -> Alchemy

def new_alchemy(
  address: str, *, alchemy_url: str, rpc_url: str | None = None,
  api_key: str | None = None, poa_middleware: bool = False
):
  if api_key is None:
    import os
    api_key = os.environ['ALCHEMY_API_KEY']
  if rpc_url is None:
    rpc_url = alchemy_url + '/' + api_key
  return AlchemyHistory.alchemy_new(
    address,
    alchemy_url=alchemy_url,
    rpc_url=rpc_url,
    api_key=api_key,
    include_internal_transfers=False,
    poa_middleware=poa_middleware,
  )

def bnb(address: str, *, alchemy_url: str = BNB_ALCHEMY_URL, rpc_url: str | None = None, api_key: str | None = None):
  return new_alchemy(address, alchemy_url=alchemy_url, rpc_url=rpc_url, api_key=api_key, poa_middleware=True)

def base(address: str, *, alchemy_url: str = BASE_ALCHEMY_URL, rpc_url: str | None = None, api_key: str | None = None):
  return new_alchemy(address, alchemy_url=alchemy_url, rpc_url=rpc_url, api_key=api_key)

def avalanche(address: str, *, alchemy_url: str = AVAX_ALCHEMY_URL, rpc_url: str | None = None, api_key: str | None = None):
  return new_alchemy(address, alchemy_url=alchemy_url, rpc_url=rpc_url, api_key=api_key, poa_middleware=True)

def optimism(address: str, *, alchemy_url: str = OPTIMISM_ALCHEMY_URL, rpc_url: str | None = None, api_key: str | None = None):
  return new_alchemy(address, alchemy_url=alchemy_url, rpc_url=rpc_url, api_key=api_key, poa_middleware=True)
