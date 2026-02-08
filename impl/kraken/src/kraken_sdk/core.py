import os
from dataclasses import dataclass
import inspect

from ccxt.async_support import kraken
from ccxt.base.errors import NetworkError, AuthenticationError, BaseError

from tribulnation.sdk.core import AuthError, Error, NetworkError

def wrap_exceptions(fn):
  if inspect.iscoroutinefunction(fn):
    async def wrapper(*args, **kwargs):
      try:
        return await fn(*args, **kwargs)
      except NetworkError as e:
        raise NetworkError(*e.args) from e
      except AuthenticationError as e:
        raise AuthError(*e.args) from e
      except BaseError as e:
        raise Error(*e.args) from e
    return wrapper
  elif inspect.isgeneratorfunction(fn):
    async def wrapper(*args, **kwargs):
      try:
        async for item in fn(*args, **kwargs):
          yield item
      except NetworkError as e:
        raise NetworkError(*e.args) from e
      except AuthenticationError as e:
          raise AuthError(*e.args) from e
      except BaseError as e:
        raise Error(*e.args) from e
    return wrapper
  else:
    raise ValueError(f"Function {fn.__name__} is not a coroutine or generator function")
    

@dataclass
class SdkMixin:
  client: kraken
  
  @classmethod
  def new(cls, api_key: str | None = None, api_secret: str | None = None):
    if api_key is None:
      api_key = os.environ['KRAKEN_API_KEY']
    if api_secret is None:
      api_secret = os.environ['KRAKEN_API_SECRET']
    client = kraken({
      'apiKey': api_key,
      'secret': api_secret,
    })
    return cls(client=client)
  
  async def __aenter__(self):
    await self.client.__aenter__()
    return self
  
  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)