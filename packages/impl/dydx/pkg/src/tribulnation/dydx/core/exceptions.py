"""Translate `typed_dydx` and gRPC exceptions into the SDK's own hierarchy at the
boundary of every venue call.
"""

from typing_extensions import (
  Any,
  AsyncGenerator,
  Callable,
  ParamSpec,
  TypeVar,
  overload,
)
from functools import wraps
from types import CoroutineType
import inspect

from grpc._channel import _InactiveRpcError

from tribulnation.sdk.core import (
  NetworkError,
  ValidationError,
  ApiError,
  Error,
  RateLimited,
)
from typed_core import exceptions as core

P = ParamSpec('P')
R = TypeVar('R')

VenueError = (core.Error, _InactiveRpcError)
"""Every exception class a `typed_dydx` call can raise through its own transports."""


def translate(e: 'core.Error | _InactiveRpcError') -> Error:
  """
  The SDK exception matching a client or gRPC exception.

  Args:
    e: The client or gRPC exception.
  """
  if isinstance(e, _InactiveRpcError):
    return ApiError(*e.args)
  if isinstance(e, core.NetworkError):
    return NetworkError(*e.args)
  if isinstance(e, core.ValidationError):
    return ValidationError(*e.args)
  if isinstance(e, core.RateLimited):
    return RateLimited(*e.args)
  if isinstance(e, core.ApiError):
    cls = RateLimited if e.args and e.args[0] == 429 else ApiError
    return cls(*e.args)
  return Error(*e.args)


@overload
def wrap_exceptions(
  fn: 'Callable[P, CoroutineType[Any, Any, R]]',
) -> 'Callable[P, CoroutineType[Any, Any, R]]': ...
@overload
def wrap_exceptions(
  fn: Callable[P, AsyncGenerator[R, Any]],
) -> Callable[P, AsyncGenerator[R, Any]]: ...
@overload
def wrap_exceptions(fn: Callable[P, R]) -> Callable[P, R]: ...
def wrap_exceptions(fn: Callable[P, Any]) -> Callable[P, Any]:
  """
  Re-raise `typed_dydx` errors escaping `fn` as SDK errors, for a coroutine function, an
  async generator function or a plain function alike. The signature is preserved as is;
  the runtime dispatch below decides how to intercept.

  Args:
    fn: The function to wrap.
  """
  if inspect.iscoroutinefunction(fn):

    @wraps(fn)
    async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
      try:
        return await fn(*args, **kwargs)
      except VenueError as e:
        raise translate(e) from e

    return async_wrapper

  if inspect.isasyncgenfunction(fn):

    @wraps(fn)
    async def gen_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
      try:
        async for item in fn(*args, **kwargs):
          yield item
      except VenueError as e:
        raise translate(e) from e

    return gen_wrapper

  @wraps(fn)
  def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
    try:
      return fn(*args, **kwargs)
    except VenueError as e:
      raise translate(e) from e

  return sync_wrapper
