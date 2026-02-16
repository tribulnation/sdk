import inspect
from functools import wraps
import httpx
import pydantic

from trading_sdk.core import NetworkError, ValidationError, ApiError, Error

from mexc import core

def wrap_exceptions(fn):

  if inspect.iscoroutinefunction(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs): # type: ignore
      try:
        return await fn(*args, **kwargs)
      except httpx.HTTPError as e:
        raise NetworkError(*e.args) from e
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except pydantic.ValidationError as e:
        raise ValidationError(*e.args) from e
      except core.ApiError as e:
        raise ApiError(*e.args) from e
      except core.Error as e:
        raise Error(*e.args) from e
      
  elif inspect.isgeneratorfunction(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs): # type: ignore
      try:
        return await fn(*args, **kwargs)
      except httpx.HTTPError as e:
        raise NetworkError(*e.args) from e
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except pydantic.ValidationError as e:
        raise ValidationError(*e.args) from e
      except core.ApiError as e:
        raise ApiError(*e.args) from e
      except core.Error as e:
        raise Error(*e.args) from e
  else:
    @wraps(fn)
    def wrapper(*args, **kwargs):
      try:
        return fn(*args, **kwargs)
      except httpx.HTTPError as e:
        raise NetworkError(*e.args) from e
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except pydantic.ValidationError as e:
        raise ValidationError(*e.args) from e
      except core.ApiError as e:
        raise ApiError(*e.args) from e
      except core.Error as e:
        raise Error(*e.args) from e
  return wrapper