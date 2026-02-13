from functools import wraps
import inspect
from tribulnation.sdk.core import NetworkError, ValidationError, ApiError, Error

from dydx import core

def wrap_exceptions(fn):
  if inspect.iscoroutinefunction(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs): # type: ignore
      try:
        return await fn(*args, **kwargs)
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except core.ValidationError as e:
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
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except core.ValidationError as e:
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
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except core.ValidationError as e:
        raise ValidationError(*e.args) from e
      except core.ApiError as e:
        raise ApiError(*e.args) from e
      except core.Error as e:
        raise Error(*e.args) from e
  return wrapper