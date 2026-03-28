from dataclasses import dataclass

from web3 import Web3
from alchemy import Transfers


@dataclass(kw_only=True)
class Mixin:
  address: str
  alchemy_transfers: Transfers

  @classmethod
  def new(cls, transfers: Transfers, address: str):
    assert Web3.is_checksum_address(address), f'{address} is not a checksum address'
    return cls(
      address=address,
      alchemy_transfers=transfers,
    )

  @classmethod
  def ethereum(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.ethereum(api_key=api_key, validate=validate)
    return cls.new(transfers, address)

  @classmethod
  def arbitrum(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.arbitrum(api_key=api_key, validate=validate)
    return cls.new(transfers, address)

  @classmethod
  def polygon(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.polygon(api_key=api_key, validate=validate)
    return cls.new(transfers, address)

  @classmethod
  def base(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.base(api_key=api_key, validate=validate)
    return cls.new(transfers, address)

  @classmethod
  def optimism(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.optimism(api_key=api_key, validate=validate)
    return cls.new(transfers, address)

  @classmethod
  def bnb(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.bnb(api_key=api_key, validate=validate)
    return cls.new(transfers, address)

  @classmethod
  def avalanche(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.avalanche(api_key=api_key, validate=validate)
    return cls.new(transfers, address)

  async def __aenter__(self):
    await self.alchemy_transfers.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.alchemy_transfers.__aexit__(exc_type, exc_value, traceback)
