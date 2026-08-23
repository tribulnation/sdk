import functools

@functools.cache
def cached_etherscan(api_key: str | None = None, *, rate_limit: int | None, validate: bool = True):
  from etherscan import Etherscan
  return Etherscan.new(api_key=api_key, validate=validate, rate_limit=rate_limit)

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()