from functools import wraps
import inspect

from grpc._channel import _InactiveRpcError

from tribulnation.sdk.core import NetworkError, ValidationError, ApiError, Error, RateLimited
from typed_core import exceptions as core

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
      except core.RateLimited as e:
        raise RateLimited(*e.args) from e
      except (core.ApiError, _InactiveRpcError) as e:
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
      except core.RateLimited as e:
        raise RateLimited(*e.args) from e
      except (core.ApiError, _InactiveRpcError) as e:
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
      except core.RateLimited as e:
        raise RateLimited(*e.args) from e
      except (core.ApiError, _InactiveRpcError) as e:
        raise ApiError(*e.args) from e
      except core.Error as e:
        raise Error(*e.args) from e
  return wrapper