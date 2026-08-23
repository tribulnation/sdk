from typing_extensions import Any, AsyncIterable, TypeVar
from functools import wraps
import inspect

from web3 import exceptions as exc
import aiohttp

from tribulnation.sdk.core import ApiError, NetworkError, RateLimited

Fn = TypeVar('Fn')

def wrap_exceptions(fn: Fn) -> Fn:
  """
  Wrap unexpected exceptions from the Ethereum dependencies into trading-sdk
  standard exceptions.
  """

  if inspect.iscoroutinefunction(fn):

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any):  # type: ignore[misc]
      try:
        return await fn(*args, **kwargs)
      except (exc.ProviderConnectionError, exc.TimeExhausted) as e:
        raise NetworkError(*e.args) from e
      except aiohttp.ClientResponseError as e:
        if e.status == 429:
          raise RateLimited(*e.args) from e
        else:
          raise ApiError(*e.args) from e
      except exc.Web3Exception as e:
        raise ApiError(*e.args) from e

    return wrapper  # type: ignore[return-value]

  if inspect.isasyncgenfunction(fn):

    @wraps(fn)
    async def agen_wrapper(*args: Any, **kwargs: Any) -> AsyncIterable[Any]:  # type: ignore[misc]
      try:
        async for item in fn(*args, **kwargs):
          yield item
      except (exc.ProviderConnectionError, exc.TimeExhausted) as e:
        raise NetworkError(*e.args) from e
      except aiohttp.ClientResponseError as e:
        if e.status == 429:
          raise RateLimited(*e.args) from e
        else:
          raise ApiError(*e.args) from e
      except exc.Web3Exception as e:
        raise ApiError(*e.args) from e

    return agen_wrapper  # type: ignore[return-value]

  if inspect.isgeneratorfunction(fn):

    @wraps(fn)
    def gen_wrapper(*args: Any, **kwargs: Any):  # type: ignore[misc]
      try:
        for item in fn(*args, **kwargs):
          yield item
      except (exc.ProviderConnectionError, exc.TimeExhausted) as e:
        raise NetworkError(*e.args) from e
      except aiohttp.ClientResponseError as e:
        if e.status == 429:
          raise RateLimited(*e.args) from e
        else:
          raise ApiError(*e.args) from e
      except exc.Web3Exception as e:
        raise ApiError(*e.args) from e

    return gen_wrapper  # type: ignore[return-value]

  if inspect.isfunction(fn) or inspect.ismethod(fn):

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):  # type: ignore[misc]
      try:
        return fn(*args, **kwargs)
      except (exc.ProviderConnectionError, exc.TimeExhausted) as e:
        raise NetworkError(*e.args) from e
      except aiohttp.ClientResponseError as e:
        if e.status == 429:
          raise RateLimited(*e.args) from e
        else:
          raise ApiError(*e.args) from e
      except exc.Web3Exception as e:
        raise ApiError(*e.args) from e

    return wrapper  # type: ignore[return-value]

  raise ValueError(f"Function {fn} is not a supported callable type for wrap_exceptions")
