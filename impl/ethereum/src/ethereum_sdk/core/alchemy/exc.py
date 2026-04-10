import inspect
from functools import wraps
from typing_extensions import TypeVar, Any, AsyncIterable

from alchemy import core

from trading_sdk.core import (
  NetworkError,
  ValidationError,
  ApiError,
  Error,
  AuthError,
)

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
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except core.ValidationError as e:
        raise ValidationError(*e.args) from e
      except core.AuthError as e:
        raise AuthError(*e.args) from e
      except core.ApiError as e:
        raise ApiError(*e.args) from e
      except core.Error as e:
        raise Error(*e.args) from e
      except Exception as e:
        raise ApiError(*e.args) from e

    return wrapper  # type: ignore[return-value]

  if inspect.isasyncgenfunction(fn):

    @wraps(fn)
    async def agen_wrapper(*args: Any, **kwargs: Any) -> AsyncIterable[Any]:  # type: ignore[misc]
      try:
        async for item in fn(*args, **kwargs):
          yield item
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except core.ValidationError as e:
        raise ValidationError(*e.args) from e
      except core.AuthError as e:
        raise AuthError(*e.args) from e
      except core.ApiError as e:
        raise ApiError(*e.args) from e
      except core.Error as e:
        raise Error(*e.args) from e
      except Exception as e:
        raise ApiError(*e.args) from e

    return agen_wrapper  # type: ignore[return-value]

  if inspect.isgeneratorfunction(fn):

    @wraps(fn)
    def gen_wrapper(*args: Any, **kwargs: Any):  # type: ignore[misc]
      try:
        for item in fn(*args, **kwargs):
          yield item
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except core.ValidationError as e:
        raise ValidationError(*e.args) from e
      except core.AuthError as e:
        raise AuthError(*e.args) from e
      except core.ApiError as e:
        raise ApiError(*e.args) from e
      except core.Error as e:
        raise Error(*e.args) from e
      except Exception as e:
        raise ApiError(*e.args) from e

    return gen_wrapper  # type: ignore[return-value]

  # Plain sync function.
  if inspect.isfunction(fn) or inspect.ismethod(fn):

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):  # type: ignore[misc]
      try:
        return fn(*args, **kwargs)
      except core.NetworkError as e:
        raise NetworkError(*e.args) from e
      except core.ValidationError as e:
        raise ValidationError(*e.args) from e
      except core.AuthError as e:
        raise AuthError(*e.args) from e
      except core.ApiError as e:
        raise ApiError(*e.args) from e
      except core.Error as e:
        raise Error(*e.args) from e
      except Exception as e:
        raise ApiError(*e.args) from e

    return wrapper  # type: ignore[return-value]

  raise ValueError(f"Function {fn} is not a supported callable type for wrap_exceptions")

