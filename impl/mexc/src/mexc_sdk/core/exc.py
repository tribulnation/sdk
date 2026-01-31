import inspect
from functools import wraps
import httpx
import pydantic

from sdk.core import NetworkError, ValidationError, ApiError

from mexc import core

def wrap_exceptions(fn):

  if inspect.iscoroutinefunction(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs): # type: ignore
      try:
        return await fn(*args, **kwargs)
      except httpx.HTTPError as e:
        raise NetworkError from e
      except pydantic.ValidationError as e:
        raise ValidationError from e
      except core.ApiError as e:
        raise ApiError from e
      
  elif inspect.isgeneratorfunction(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs): # type: ignore
      try:
        return await fn(*args, **kwargs)
      except httpx.HTTPError as e:
        raise NetworkError from e
      except pydantic.ValidationError as e:
        raise ValidationError from e
      except core.ApiError as e:
        raise ApiError from e
  else:
    @wraps(fn)
    def wrapper(*args, **kwargs):
      try:
        return fn(*args, **kwargs)
      except httpx.HTTPError as e:
        raise NetworkError from e
      except pydantic.ValidationError as e:
        raise ValidationError from e
      except core.ApiError as e:
        raise ApiError from e
  return wrapper