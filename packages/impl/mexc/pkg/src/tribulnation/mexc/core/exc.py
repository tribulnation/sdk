"""Translate `typed_mexc` and transport exceptions into the SDK's own hierarchy at the
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

import httpx
import pydantic

from tribulnation.sdk.core import (
  NetworkError,
  ValidationError,
  Error,
  translate_exception,
)

from typed_core import exceptions as core

P = ParamSpec('P')
R = TypeVar('R')

VenueError = (httpx.HTTPError, pydantic.ValidationError, core.Error)
"""Every exception class a `typed_mexc` call can raise through its own transport."""


def translate(e: 'httpx.HTTPError | pydantic.ValidationError | core.Error') -> Error:
  """
  The SDK exception matching a client or transport exception.

  Args:
    e: The client or transport exception.
  """
  if isinstance(e, httpx.HTTPError):
    return NetworkError(*e.args)
  if isinstance(e, pydantic.ValidationError):
    return ValidationError(*e.args)
  translated = translate_exception(e)
  if translated is not None:
    return translated
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
  Re-raise `typed_mexc` errors escaping `fn` as SDK errors, for a coroutine function, an
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
