from dataclasses import dataclass

from etherscan import Etherscan, ETHERSCAN_API_URL

@dataclass(kw_only=True)
class Mixin:
  etherscan: Etherscan
  chain_id: int
  address: str

  @classmethod
  def etherscan_new(
    cls, address: str, chain_id: int, *, api_key: str | None = None,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True, rate_limit: int | None = None
  ):
    etherscan = Etherscan.new(api_key=api_key, base_url=base_url, validate=validate, rate_limit=rate_limit)
    return cls(etherscan=etherscan, chain_id=chain_id, address=address)

  @classmethod
  def etherscan_ethereum(
    cls, address: str, *, api_key: str | None = None,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
    rate_limit: int | None = None,
  ):
    return cls.etherscan_new(address, 1, api_key=api_key, base_url=base_url, validate=validate, rate_limit=rate_limit)

  @classmethod
  def etherscan_arbitrum(
    cls, address: str, *, api_key: str | None = None,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
    rate_limit: int | None = None,
  ):
    return cls.etherscan_new(address, 42161, api_key=api_key, base_url=base_url, validate=validate, rate_limit=rate_limit)

  @classmethod
  def etherscan_polygon(
    cls, address: str, *, api_key: str | None = None,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
    rate_limit: int | None = None,
  ):
    return cls.etherscan_new(address, 137, api_key=api_key, base_url=base_url, validate=validate, rate_limit=rate_limit)

  async def __aenter__(self):
    await self.etherscan.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.etherscan.__aexit__(exc_type, exc_value, traceback)
