from typing_extensions import Callable, TypeVar
from functools import wraps
import inspect
import typed_core

Fn = TypeVar('Fn')


class Error(Exception):
  """Base SDK exception."""

  def __str__(self):
    args = self.args[0] if len(self.args) == 1 else ', '.join(map(str, self.args))
    return f'{self.__class__.__name__}({args})'


class NetworkError(Error):
  """Error reaching the server."""

  def __str__(self):
    return super().__str__()


class ValidationError(Error):
  """Invalid response format."""

  def __str__(self):
    return super().__str__()


class ApiError(Error):
  """Error returned by the API."""

  def __str__(self):
    return super().__str__()


class BadRequest(ApiError):
  """Bad request: invalid request, invalid input, etc."""

  def __str__(self):
    return super().__str__()


class AuthError(ApiError):
  """Authentication error: invalid API key, invalid API secret, etc."""

  def __str__(self):
    return super().__str__()


class RateLimited(ApiError):
  """Rate limited: the API has reached the rate limit."""

  def __str__(self):
    return super().__str__()


class LogicError(Error):
  """Logic error: invalid assumptions, logic, or other bugs on the SDK side."""

  def __str__(self):
    return super().__str__()


def translate_exception(e: Exception) -> Error | None:
  """
  Map a `typed_core` exception to its `tribulnation.sdk.core.exc` equivalent.
  Returns `None` for exceptions outside the `typed_core` hierarchy.
  """
  if isinstance(e, typed_core.BadRequest):
    return BadRequest(*e.args)
  if isinstance(e, typed_core.AuthError):
    return AuthError(*e.args)
  if isinstance(e, typed_core.RateLimited):
    return RateLimited(*e.args)
  if isinstance(e, typed_core.ApiError):
    return ApiError(*e.args)
  if isinstance(e, typed_core.NetworkError):
    return NetworkError(*e.args)
  if isinstance(e, typed_core.ValidationError):
    return ValidationError(*e.args)
  if isinstance(e, typed_core.LogicError):
    return LogicError(*e.args)
  if isinstance(e, typed_core.Error):
    return Error(*e.args)


def exception_wrapper(
  translate: Callable[[Exception], Error | None] = translate_exception,
) -> Callable[[Fn], Fn]:
  """
  Build a decorator that funnels exceptions raised by a function through
  `translate`, dispatching on whether the function is sync, async, a
  generator, or an async generator.

  Args:
    translate: Maps a caught exception to the SDK exception to raise instead,
      or `None` to let the original exception propagate unchanged. Defaults
      to `translate_exception`, which maps `typed_core`'s exception hierarchy.
  """

  def decorator(fn: Fn) -> Fn:
    if inspect.iscoroutinefunction(fn):

      @wraps(fn)
      async def awrapper(*args, **kwargs):
        try:
          return await fn(*args, **kwargs)
        except Exception as e:
          mapped = translate(e)
          if mapped is None:
            raise
          raise mapped from e

      return awrapper  # type: ignore

    if inspect.isasyncgenfunction(fn):

      @wraps(fn)
      async def agen_wrapper(*args, **kwargs):
        try:
          async for item in fn(*args, **kwargs):
            yield item
        except Exception as e:
          mapped = translate(e)
          if mapped is None:
            raise
          raise mapped from e

      return agen_wrapper  # type: ignore

    if inspect.isgeneratorfunction(fn):

      @wraps(fn)
      def gen_wrapper(*args, **kwargs):
        try:
          yield from fn(*args, **kwargs)
        except Exception as e:
          mapped = translate(e)
          if mapped is None:
            raise
          raise mapped from e

      return gen_wrapper  # type: ignore

    if inspect.isfunction(fn) or inspect.ismethod(fn):

      @wraps(fn)
      def wrapper(*args, **kwargs):
        try:
          return fn(*args, **kwargs)
        except Exception as e:
          mapped = translate(e)
          if mapped is None:
            raise
          raise mapped from e

      return wrapper  # type: ignore

    raise ValueError(
      f'Function {fn} is not a supported callable type for exception_wrapper'
    )

  return decorator
