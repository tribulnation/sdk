from functools import wraps
import inspect
from tribulnation.sdk.core import NetworkError, ValidationError

from dydx import core

def wrap_exceptions(fn):
  if inspect.iscoroutinefunction(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs): # type: ignore
      try:
        return await fn(*args, **kwargs)
      except core.NetworkError as e:
        raise NetworkError from e
      except core.ValidationError as e:
        raise ValidationError from e
      
  elif inspect.isgeneratorfunction(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs): # type: ignore
      try:
        return await fn(*args, **kwargs)
      except core.NetworkError as e:
        raise NetworkError from e
      except core.ValidationError as e:
        raise ValidationError from e
      
  else:
    @wraps(fn)
    def wrapper(*args, **kwargs):
      try:
        return fn(*args, **kwargs)
      except core.NetworkError as e:
        raise NetworkError from e
      except core.ValidationError as e:
        raise ValidationError from e
  return wrapper