from dataclasses import dataclass

from web3 import Web3
from ethereum.etherscan import Etherscan, ETHERSCAN_API_URL

@dataclass(kw_only=True)
class EtherscanMixin:
  etherscan: Etherscan
  address: str
  chain_id: int
  ignore_zero_value: bool = True

  @classmethod
  def new(
    cls, api_key: str | None = None, *, address: str, chain_id: int,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
    ignore_zero_value: bool = True,
  ):
    assert Web3.is_checksum_address(address), f'{address} is not a checksum address'
    etherscan = Etherscan.new(api_key=api_key, base_url=base_url, validate=validate)
    return cls(etherscan=etherscan, address=address, chain_id=chain_id, ignore_zero_value=ignore_zero_value)

  @classmethod
  def ethereum(
    cls, api_key: str | None = None, *, address: str,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
    ignore_zero_value: bool = True,
  ):
    return cls.new(api_key=api_key, address=address, chain_id=1, base_url=base_url, validate=validate, ignore_zero_value=ignore_zero_value)

  @classmethod
  def arbitrum(
    cls, api_key: str | None = None, *, address: str,
    base_url: str = ETHERSCAN_API_URL, validate: bool = True,
    ignore_zero_value: bool = True,
  ):
    return cls.new(api_key=api_key, address=address, chain_id=42161, base_url=base_url, validate=validate, ignore_zero_value=ignore_zero_value)

  async def __aenter__(self):
    await self.etherscan.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.etherscan.__aexit__(exc_type, exc_value, traceback)
