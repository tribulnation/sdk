import os
from dataclasses import dataclass

from mexc import MEXC


@dataclass
class SdkMixin:
  client: MEXC
  validate: bool = True
  recvWindow: int | None = None

  @classmethod
  def new(
    cls, api_key: str | None = None, api_secret: str | None = None, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    if api_key is None:
      api_key = os.environ['MEXC_ACCESS_KEY']
    if api_secret is None:
      api_secret = os.environ['MEXC_SECRET_KEY']
    client = MEXC.new(api_key=api_key, api_secret=api_secret)
    return cls(client=client, validate=validate, recvWindow=recvWindow)

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)


@dataclass(kw_only=True)
class MarketMixin(SdkMixin):
  instrument: str