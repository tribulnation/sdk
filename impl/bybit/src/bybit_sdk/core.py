from typing_extensions import Literal
from dataclasses import dataclass
import inspect
import os

from ccxt.async_support import bybit
from ccxt.base.errors import NetworkError as CcxtNetworkError, AuthenticationError, BaseError

from trading_sdk.core import AuthError, Error, NetworkError


def wrap_exceptions(fn):
  if inspect.iscoroutinefunction(fn):
    async def wrapper(*args, **kwargs):
      try:
        return await fn(*args, **kwargs)
      except CcxtNetworkError as e:
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
      except CcxtNetworkError as e:
        raise NetworkError(*e.args) from e
      except AuthenticationError as e:
        raise AuthError(*e.args) from e
      except BaseError as e:
        raise Error(*e.args) from e
    return wrapper
  else:
    raise ValueError(f"Function {fn.__name__} is not a coroutine or generator function")

Platform = Literal['bybit', 'bybit_eu']

@dataclass
class SdkMixin:
  client: bybit
  platform: Platform

  @classmethod
  def new(cls, *, platform: Platform = 'bybit', api_key: str | None = None, api_secret: str | None = None):
    if api_key is None:
      api_key = os.environ.get('BYBIT_API_KEY')
    if api_secret is None:
      api_secret = os.environ.get('BYBIT_API_SECRET')
    config = {}
    if api_key is not None:
      config['apiKey'] = api_key
    if api_secret is not None:
      config['secret'] = api_secret
    if platform == 'bybit_eu':
      config['hostname'] = 'bybit.eu'
    client = bybit(config)
    return cls(client=client, platform=platform)

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)
