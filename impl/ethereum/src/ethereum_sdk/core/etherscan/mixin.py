from dataclasses import dataclass

from etherscan import Etherscan, ETHERSCAN_API_URL

@dataclass(kw_only=True)
class Mixin:
  etherscan: Etherscan
  chain_id: int

  @classmethod
  def new(
    cls, chain_id: int, *, api_key: str | None = None,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
  ):
    etherscan = Etherscan.new(api_key=api_key, base_url=base_url, validate=validate)
    return cls(etherscan=etherscan, chain_id=chain_id)

  @classmethod
  def ethereum(
    cls, *, api_key: str | None = None,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
  ):
    return cls.new(1, api_key=api_key, base_url=base_url, validate=validate)

  @classmethod
  def arbitrum(
    cls, *, api_key: str | None = None,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
  ):
    return cls.new(42161, api_key=api_key, base_url=base_url, validate=validate)

  @classmethod
  def polygon(
    cls, *, api_key: str | None = None,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
  ):
    return cls.new(137, api_key=api_key, base_url=base_url, validate=validate)

  async def __aenter__(self):
    await self.etherscan.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.etherscan.__aexit__(exc_type, exc_value, traceback)
