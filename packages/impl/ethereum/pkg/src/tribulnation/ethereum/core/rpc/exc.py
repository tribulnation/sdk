from typing_extensions import Any, AsyncIterable, TypeVar
from functools import wraps
import inspect

from web3 import exceptions as exc
import aiohttp

from tribulnation.sdk.core import ApiError, Error, NetworkError, RateLimited

Fn = TypeVar('Fn')


def translate(e: Exception) -> Error | None:
  """
  Map an exception from the Ethereum dependencies onto its SDK equivalent.

  Returns `None` for anything outside the dependencies' own hierarchies, which the
  wrappers below let propagate unchanged.
  """
  if isinstance(e, exc.ProviderConnectionError | exc.TimeExhausted):
    return NetworkError(*e.args)
  if isinstance(e, aiohttp.ClientResponseError):
    message = f'{e.status} {e.message} for {origin(e)}'
    return RateLimited(message) if e.status == 429 else ApiError(message)
  if isinstance(e, exc.Web3Exception):
    return ApiError(*e.args)


def origin(e: aiohttp.ClientResponseError) -> str:
  """
  The request's method and origin, without the path or query.

  `ClientResponseError.args` is `(RequestInfo, history)`, and that `RequestInfo` reprs
  the full URL. For the providers this client talks to that URL *is* the credential:
  Alchemy carries the API key as its final path segment, Etherscan as an `apikey` query
  parameter. Forwarding it would put the key into every log, traceback and crash report
  that ever renders the exception, so only the origin travels.
  """
  url = e.request_info.url
  return f'{e.request_info.method} {url.scheme}://{url.host}'


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
      except Exception as e:
        mapped = translate(e)
        if mapped is None:
          raise
        raise mapped from e

    return wrapper  # type: ignore[return-value]

  if inspect.isasyncgenfunction(fn):

    @wraps(fn)
    async def agen_wrapper(*args: Any, **kwargs: Any) -> AsyncIterable[Any]:  # type: ignore[misc]
      try:
        async for item in fn(*args, **kwargs):
          yield item
      except Exception as e:
        mapped = translate(e)
        if mapped is None:
          raise
        raise mapped from e

    return agen_wrapper  # type: ignore[return-value]

  if inspect.isgeneratorfunction(fn):

    @wraps(fn)
    def gen_wrapper(*args: Any, **kwargs: Any):  # type: ignore[misc]
      try:
        for item in fn(*args, **kwargs):
          yield item
      except Exception as e:
        mapped = translate(e)
        if mapped is None:
          raise
        raise mapped from e

    return gen_wrapper  # type: ignore[return-value]

  if inspect.isfunction(fn) or inspect.ismethod(fn):

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):  # type: ignore[misc]
      try:
        return fn(*args, **kwargs)
      except Exception as e:
        mapped = translate(e)
        if mapped is None:
          raise
        raise mapped from e

    return wrapper  # type: ignore[return-value]

  raise ValueError(
    f'Function {fn} is not a supported callable type for wrap_exceptions'
  )
