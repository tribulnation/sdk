from dataclasses import dataclass

from binance import Binance

@dataclass
class SdkMixin:
  client: Binance
  validate: bool = True

  @classmethod
  def new(
    cls, api_key: str | None = None, api_secret: str | None = None, *,
    validate: bool = True
  ):
    client = Binance.new(api_key=api_key, api_secret=api_secret, validate=validate)
    return cls(client=client, validate=validate)

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)