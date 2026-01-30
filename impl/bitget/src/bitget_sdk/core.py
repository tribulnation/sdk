from dataclasses import dataclass

from bitget import Bitget


@dataclass
class SdkMixin:
  client: Bitget
  validate: bool = True

  @classmethod
  def new(
    cls, access_key: str | None = None, secret_key: str | None = None, passphrase: str | None = None, *,
    validate: bool = True
  ):
    client = Bitget.new(access_key=access_key, secret_key=secret_key, passphrase=passphrase)
    return cls(client=client, validate=validate)

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)