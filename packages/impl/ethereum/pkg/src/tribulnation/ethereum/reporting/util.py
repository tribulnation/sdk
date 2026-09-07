import functools


@functools.cache
def cached_etherscan(
  api_key: str | None = None, *, rate_limit: int | None = None, validate: bool = True
):
  """Build an Etherscan client once per argument set, shared across sources."""
  from typed_etherscan import Etherscan

  return Etherscan.new(api_key=api_key, validate=validate, rate_limit=rate_limit)
