import os
from dataclasses import dataclass

from ccxt.async_support import bingx

@dataclass
class SdkMixin:
  client: bingx
  
  @classmethod
  def new(cls, api_key: str | None = None, api_secret: str | None = None):
    if api_key is None:
      api_key = os.environ['BINGX_API_KEY']
    if api_secret is None:
      api_secret = os.environ['BINGX_SECRET_KEY']
    client = bingx({
      'apiKey': api_key,
      'secret': api_secret,
    })
    return cls(client=client)
  
  async def __aenter__(self):
    await self.client.__aenter__()
    return self
  
  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)