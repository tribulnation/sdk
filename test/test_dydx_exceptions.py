from collections.abc import AsyncIterator

import pytest
from typed_core import exceptions as core

from tribulnation.dydx.core import wrap_exceptions
from tribulnation.sdk.core import ApiError, Context, RateLimited, SDK


def _underlying_error(status: int) -> core.ApiError:
  return core.ApiError(status, {'code': status, 'msg': 'request failed'})


async def test_wrap_exceptions_maps_http_429_to_rate_limited() -> None:
  source = _underlying_error(429)

  @wrap_exceptions
  async def fail() -> None:
    raise source

  with pytest.raises(RateLimited) as raised:
    await fail()

  assert raised.value.args == source.args
  assert raised.value.__cause__ is source


async def test_wrap_exceptions_keeps_other_api_errors_generic() -> None:
  source = _underlying_error(503)

  @wrap_exceptions
  async def fail() -> None:
    raise source

  with pytest.raises(ApiError) as raised:
    await fail()

  assert type(raised.value) is ApiError
  assert raised.value.args == source.args
  assert raised.value.__cause__ is source


def test_wrap_exceptions_maps_sync_http_429_to_rate_limited() -> None:
  @wrap_exceptions
  def fail() -> None:
    raise _underlying_error(429)

  with pytest.raises(RateLimited):
    fail()


async def test_wrap_exceptions_maps_async_generator_http_429_to_rate_limited() -> None:
  @wrap_exceptions
  async def fail() -> AsyncIterator[None]:
    if False:
      yield
    raise _underlying_error(429)

  with pytest.raises(RateLimited):
    await anext(fail())


async def test_external_context_retries_translated_rate_limit() -> None:
  class Retriable(SDK):
    def __init__(self) -> None:
      self.calls = 0

    @SDK.method
    @wrap_exceptions
    async def fetch(self) -> str:
      self.calls += 1
      if self.calls == 1:
        raise _underlying_error(429)
      return 'ok'

  target = Retriable()
  with Context().retried(RateLimited, max_retries=1, base_delay=0).use():
    assert await target.fetch() == 'ok'
  assert target.calls == 2
