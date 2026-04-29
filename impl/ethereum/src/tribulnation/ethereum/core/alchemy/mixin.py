from dataclasses import dataclass

from alchemy import Transfers

@dataclass(kw_only=True)
class Mixin:
  address: str
  alchemy_transfers: Transfers

  @classmethod
  def alchemy_ethereum(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.ethereum(api_key=api_key, validate=validate)
    return cls(address=address, alchemy_transfers=transfers)

  @classmethod
  def alchemy_arbitrum(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.arbitrum(api_key=api_key, validate=validate)
    return cls(address=address, alchemy_transfers=transfers)

  @classmethod
  def alchemy_polygon(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.polygon(api_key=api_key, validate=validate)
    return cls(address=address, alchemy_transfers=transfers)

  @classmethod
  def alchemy_base(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.base(api_key=api_key, validate=validate)
    return cls(address=address, alchemy_transfers=transfers)

  @classmethod
  def alchemy_optimism(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.optimism(api_key=api_key, validate=validate)
    return cls(address=address, alchemy_transfers=transfers)

  @classmethod
  def alchemy_bnb(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.bnb(api_key=api_key, validate=validate)
    return cls(address=address, alchemy_transfers=transfers)

  @classmethod
  def alchemy_avalanche(cls, address: str, *, api_key: str | None = None, validate: bool = True):
    transfers = Transfers.avalanche(api_key=api_key, validate=validate)
    return cls(address=address, alchemy_transfers=transfers)

  async def __aenter__(self):
    await self.alchemy_transfers.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.alchemy_transfers.__aexit__(exc_type, exc_value, traceback)
