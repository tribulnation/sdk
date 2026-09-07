"""Translate `typed_bybit` failures onto the SDK's own exception hierarchy."""

import httpx
import pydantic

from tribulnation.sdk.core import (
  Error,
  NetworkError,
  ValidationError,
  exception_wrapper,
  translate_exception,
)


def translate(e: Exception) -> Error | None:
  """Map one Bybit client exception onto its SDK equivalent.

  `typed_bybit`'s envelope already raises the right `typed_core` class for every
  non-zero `retCode` (auth, rate limit, bad request), so the bulk of the work is
  `translate_exception`'s. Only the two exceptions that escape the client's own
  wrapping -- a transport failure from `httpx` and a response that fails pydantic
  validation -- need mapping here.
  """
  if isinstance(e, httpx.HTTPError):
    return NetworkError(*e.args)
  if isinstance(e, pydantic.ValidationError):
    return ValidationError(*e.args)
  return translate_exception(e)


wrap_exceptions = exception_wrapper(translate)
"""Decorate a function so Bybit client failures surface as SDK exceptions."""
